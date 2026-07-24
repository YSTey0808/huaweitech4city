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
     frames it to the LLM as a human signal to weigh (and disables the
     SKIP_LLM_BELOW cost short-circuit -- a report exists precisely to
     challenge a low score). The reported message needs no special
     forced-inclusion handling: the LLM already sees every message in the
     window, not a filtered subset (see pipeline/inference.py's
     rank_messages), and the window is anchored on the reported message
     per point 1 above, so it's guaranteed present regardless.
  3. Resulting rows are written with source='user_report' (vs 'model') so
     report-triggered findings stay distinguishable -- the audit trail.

The message_reports row itself is inserted by the frontend directly
(RLS-guarded), not here -- this service only runs the re-scoring. The
Edge Function has already verified the caller's membership before this
is reached, but msg_id is still re-checked against conversation_id below
(fetch_message_window returns [] on a mismatched anchor) since the
backend must not trust a caller-supplied pairing.
"""

from .scoring_service import fetch_message_window, write_scores


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
    result = score_conversation(
        conversation_id, messages, model,
        user_report={"message_id": msg_id, "reason": reason},
    )
    return write_scores(supabase, conversation_id, result, source="user_report")
