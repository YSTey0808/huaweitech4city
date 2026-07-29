"""
Orchestrates one /report request -- the human-feedback loop's immediate
half, in both directions (migration 010's claim):

  claim='harmful' -- "the model missed this." Window is re-scored with the
      report as context; if the LLM agrees, score rows are written with
      source='user_report' (see scoring_service.write_scores).
  claim='safe' -- "the model flagged this wrongly" (false-positive
      dispute). Same re-scoring, dispute-framed prompt; if the LLM agrees
      the message is harmless, the flag is ANNULLED: its message_scores
      rows are deleted and it is pruned from any conversation_scores
      evidence list (row deleted outright if that empties it). The audit
      trail survives in message_reports (claim + status + reasoning) --
      score rows only ever reflect the current live verdict, history lives
      in the reports log. A rejected dispute changes nothing: existing
      rows keep their original source (never re-stamped 'user_report',
      which is reserved for human-confirmed HARM).

Both directions share the mechanics: the window is anchored to END at the
reported message (fetch_message_window's up_to_message_id -- an older
message would otherwise fall outside the scored window entirely), the
report is passed to the pipeline as prompt context (no forced-inclusion
needed; the LLM sees every message in the window, see
pipeline/inference.py's rank_messages), and afterwards the report row is
stamped with its outcome (status / outcome_reasoning / resolved_at,
migration 009) so the reporter's client streams the verdict over Realtime.
"confirmed" always means "the LLM agreed with the CLAIM" -- for a dispute
that's a 'safe' verdict, the inverse of a report.

The message_reports row itself is inserted by the frontend directly
(RLS-guarded), not here -- this service only runs the re-scoring and
outcome. The Edge Function has already verified the caller's membership,
but msg_id is still re-checked against conversation_id
(fetch_message_window returns [] on a mismatched anchor) since the
backend must not trust a caller-supplied pairing.
"""

from datetime import datetime, timezone

from .scoring_service import SAFE_LABEL, fetch_message_window, write_scores
from .watchlist_service import SupabaseWatchlist


def _record_report_outcome(supabase, conversation_id: str, msg_id: str, claim: str,
                            confirmed: bool, reasoning: str) -> str:
    """Stamps the pending report row(s) for this message and CLAIM direction
    with the review outcome. Keyed by (conversation_id, msg_id, claim,
    status='pending'), not reporter -- if several members filed the same
    kind of report on the same message they share the verdict, but an older
    already-resolved report in the OTHER direction (e.g. a past harmful
    report on a message now being disputed) is left untouched, so its audit
    fields aren't overwritten by an unrelated review. Failure-isolated like
    the watchlist fetch: the scoring side effects already happened, so a
    failed stamp must not fail the request (the report just stays 'pending'
    and the UI keeps showing "awaiting review")."""
    status = "confirmed" if confirmed else "dismissed"
    try:
        supabase.table("message_reports").update({
            "status": status,
            # On a rejection the prompt asks the LLM to address the
            # reporter's stated reason in gentle_alert_text (see
            # gnn/llm_stage.py) -- that sentence doubles as the outcome
            # explanation here.
            "outcome_reasoning": reasoning,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("conversation_id", conversation_id).eq("msg_id", msg_id) \
          .eq("claim", claim).eq("status", "pending").execute()
    except Exception as e:
        print(f"recording report outcome failed (report stays pending): {e}")
    return status


def _annul_message_flags(supabase, conversation_id: str, msg_id: str) -> None:
    """Confirmed false positive: remove the wrong flag so the UI clears.
    Deletes the message's message_scores rows and prunes it from every
    conversation_scores evidence list, deleting a conversation row outright
    when that was its only evidence. The dispute's own message_reports row
    (claim/status/reasoning) is the durable audit record of this action."""
    supabase.table("message_scores").delete().eq("msg_id", msg_id).execute()

    conv_res = (
        supabase.table("conversation_scores")
        .select("id, evidence_msg_ids")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    for row in conv_res.data:
        evidence = row.get("evidence_msg_ids") or []
        if msg_id not in evidence:
            continue
        remaining = [mid for mid in evidence if mid != msg_id]
        if remaining:
            supabase.table("conversation_scores").update(
                {"evidence_msg_ids": remaining}
            ).eq("id", row["id"]).execute()
        else:
            supabase.table("conversation_scores").delete().eq("id", row["id"]).execute()


def report_message_request(
    conversation_id: str,
    msg_id: str,
    reason: str,
    supabase,
    embed_model,
    model,
    embedding_store,
    model_version: str,
    claim: str = "harmful",
) -> dict:
    messages = fetch_message_window(supabase, conversation_id, up_to_message_id=msg_id)
    if not messages:
        # Unknown msg_id, or msg_id not in this conversation
        return {"conversation_scores": "message_not_found", "message_scores_inserted": 0}

    from inference import score_conversation  # pipeline/, on sys.path -- see app/main.py

    messages = embedding_store.get_or_compute(messages, embed_model, model_version)
    # Past confirmed reports as reference patterns, same as the automatic
    # path. The report being processed right now is still 'pending' (its
    # outcome is stamped below), so it can't appear in its own examples.
    confirmed_examples = SupabaseWatchlist(supabase).get_confirmed_examples()
    result = score_conversation(
        conversation_id, messages, model,
        user_report={"message_id": msg_id, "reason": reason, "claim": claim},
        confirmed_examples=confirmed_examples,
    )

    verdict_safe = result["conversation_label"] == SAFE_LABEL
    reasoning = result.get("gentle_alert_text")

    if claim == "safe":
        # Dispute: never write score rows (a safe verdict writes nothing by
        # convention, and a harmful verdict here means the EXISTING flag
        # stands as-is -- re-writing it would wrongly stamp it
        # source='user_report', which is reserved for human-confirmed harm).
        if verdict_safe:
            _annul_message_flags(supabase, conversation_id, msg_id)
            out = {"conversation_scores": "annulled", "message_scores_inserted": 0}
        else:
            out = {"conversation_scores": "flag_stands", "message_scores_inserted": 0}
        confirmed = verdict_safe
    else:
        out = write_scores(supabase, conversation_id, result, source="user_report")
        confirmed = not verdict_safe

    out["report_status"] = _record_report_outcome(
        supabase, conversation_id, msg_id, claim, confirmed, reasoning)
    return out
