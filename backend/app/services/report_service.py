"""
Orchestrates one /report request -- the human-feedback loop's immediate
half. Mirrors scoring_service.score_conversation_request() stage for
stage (fetch window -> attach embeddings -> pipeline -> write scores),
with three deliberate differences:

  1. The message window is anchored to END at the reported message
     (fetch_message_window's up_to_message_id) -- a report on a message
     older than the last WINDOW_SIZE would otherwise score a window that
     doesn't even contain it.
  2. The report ({message_id, reason}) is passed into the pipeline, which
     frames it to the LLM as a human signal to weigh. The reported message
     needs no special forced-inclusion handling: the LLM already sees every
     message in the window on every call, not a filtered subset (see
     pipeline/inference.py's rank_messages), and the window is anchored on
     the reported message per point 1 above, so it's guaranteed present
     regardless.
  3. Resulting rows are written with source='user_report' (vs 'model') so
     report-triggered findings stay distinguishable -- the audit trail.

The message_reports row itself is inserted by the frontend directly
(RLS-guarded), not here -- this service only runs the re-scoring, then
stamps the report row's outcome (status / outcome_reasoning / resolved_at,
see migration 009) so the reporter's client can stream the verdict over
Realtime instead of a dismissal vanishing into silence. The Edge Function
has already verified the caller's membership before this is reached, but
msg_id is still re-checked against conversation_id below
(fetch_message_window returns [] on a mismatched anchor) since the
backend must not trust a caller-supplied pairing.
"""

from datetime import datetime, timezone

from .scoring_service import SAFE_LABEL, fetch_message_window, write_scores
from .watchlist_service import SupabaseWatchlist


def _record_report_outcome(supabase, conversation_id: str, msg_id: str, result: dict) -> str:
    """Stamps the report row(s) for msg_id with the LLM's verdict. Keyed by
    (conversation_id, msg_id), not reporter -- if several members reported
    the same message, they all get the same outcome. Failure-isolated like
    the watchlist fetch: scores were already written, so a failed stamp
    must not fail the request (the report just stays 'pending' and the UI
    keeps showing "awaiting review")."""
    status = "dismissed" if result["conversation_label"] == SAFE_LABEL else "confirmed"
    try:
        supabase.table("message_reports").update({
            "status": status,
            # On dismissal the prompt asks the LLM to address the reporter's
            # stated reason in gentle_alert_text (see gnn/llm_stage.py) --
            # that same sentence doubles as the outcome explanation here.
            "outcome_reasoning": result.get("gentle_alert_text"),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("conversation_id", conversation_id).eq("msg_id", msg_id).execute()
    except Exception as e:
        print(f"recording report outcome failed (report stays pending): {e}")
    return status


def report_message_request(
    conversation_id: str,
    msg_id: str,
    reason: str,
    supabase,
    embed_model,
    model,
    embedding_store,
    model_version: str,
) -> dict:
    messages = fetch_message_window(supabase, conversation_id, up_to_message_id=msg_id)
    if not messages:
        # Unknown msg_id, or msg_id not in this conversation
        return {"conversation_scores": "message_not_found", "message_scores_inserted": 0}

    from inference import score_conversation  # pipeline/, on sys.path -- see app/main.py

    messages = embedding_store.get_or_compute(messages, embed_model, model_version)
    # Past confirmed reports as reference patterns, same as the automatic
    # path. The report being processed right now is not yet confirmed (its
    # score rows don't exist until write_scores below), so it can't appear
    # in its own examples list.
    confirmed_examples = SupabaseWatchlist(supabase).get_confirmed_examples()
    result = score_conversation(
        conversation_id, messages, model,
        user_report={"message_id": msg_id, "reason": reason},
        confirmed_examples=confirmed_examples,
    )
    out = write_scores(supabase, conversation_id, result, source="user_report")
    out["report_status"] = _record_report_outcome(supabase, conversation_id, msg_id, result)
    return out
