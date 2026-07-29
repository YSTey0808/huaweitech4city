"""
Orchestrates one /score request: fetch the message window from Supabase,
translate rows to the pipeline's canonical shape, attach embeddings
(cached where possible), run the pipeline, translate the verdict back into
message_scores / conversation_scores rows, and write them -- mirroring the
original mock Edge Function's window + dedup-before-insert behaviour, but
backed by the real model.
"""

from .message_mapper import supabase_row_to_pipeline_message
from .watchlist_service import SupabaseWatchlist

WINDOW_SIZE = 10

# gnn/config.py's CONV_LABELS is ["safe", "harmful"] -- absence of rows means
# safe, matching the original mock's "nothing fired -> write nothing".
SAFE_LABEL = "safe"


def fetch_message_window(supabase, conversation_id: str, window_size: int = WINDOW_SIZE,
                          up_to_message_id: str = None) -> list:
    """
    Last `window_size` messages, chronological. up_to_message_id anchors the
    window to END at that message instead of "now" -- the user-report path
    needs this, otherwise a report on a message older than the last
    `window_size` would fetch a window that doesn't even contain it.
    Returns [] if the anchor message doesn't exist in this conversation.
    """
    query = (
        supabase.table("messages")
        .select("id, sender_id, content, reply_to, created_at")
        .eq("conversation_id", conversation_id)
    )
    if up_to_message_id is not None:
        anchor_res = (
            supabase.table("messages")
            .select("created_at")
            .eq("id", up_to_message_id)
            .eq("conversation_id", conversation_id)  # anchor must belong to this conversation
            .execute()
        )
        if not anchor_res.data:
            return []
        query = query.lte("created_at", anchor_res.data[0]["created_at"])

    res = query.order("created_at", desc=True).limit(window_size).execute()
    rows = list(reversed(res.data))  # chronological order, oldest first (build_message_graph expects this)
    return [supabase_row_to_pipeline_message(row) for row in rows]


def write_scores(supabase, conversation_id: str, result: dict, source: str = "model") -> dict:
    """source: 'model' (automatic scoring) or 'user_report' (report-triggered
    re-run) -- written onto every row for audit-trail provenance, see
    migration 008."""
    label = result["conversation_label"]
    if label == SAFE_LABEL:
        # Nothing fired -> write nothing; existing rows are never deleted or downgraded.
        return {"conversation_scores": "safe", "message_scores_inserted": 0}

    evidence = result.get("top_evidence_messages", [])
    evidence_msg_ids = [e["message_id"] for e in evidence]

    # Avoid maybe_single() -- known to raise on zero rows in some supabase-py
    # versions (https://github.com/supabase/supabase-py/issues/1207);
    # a plain select + length check sidesteps it entirely.
    existing_res = (
        supabase.table("conversation_scores")
        .select("id, source")
        .eq("conversation_id", conversation_id)
        .eq("label", label)
        .execute()
    )
    # source is sticky one-directionally: once a row has been human-confirmed
    # (user_report), a later automatic pass that independently agrees on the
    # same label must not downgrade it back to 'model' -- that would silently
    # erase the "a human caught this" audit trail the column exists for. Only
    # 'model' -> 'user_report' is ever allowed, never the reverse.
    effective_source = source
    if existing_res.data and existing_res.data[0]["source"] == "user_report":
        effective_source = "user_report"

    payload = {
        "conversation_id": conversation_id,
        "label": label,
        "confidence": result["conversation_confidence"],
        "evidence_msg_ids": evidence_msg_ids,
        "severity": result.get("severity"),
        "reasoning": result.get("gentle_alert_text"),
        "source": effective_source,
    }
    if existing_res.data:
        supabase.table("conversation_scores").update(payload).eq("id", existing_res.data[0]["id"]).execute()
        conversation_status = "updated"
    else:
        supabase.table("conversation_scores").insert(payload).execute()
        conversation_status = "inserted"

    # message_scores: one row per evidence message the LLM chose to cite (see
    # gnn/llm_stage.py -- it judges from the full window, not a GNN-filtered
    # subset), using the same conversation-level label (there is no
    # independent per-message label; the GNN's per-message scores are a
    # contribution-to-the-verdict signal, not a separate classification).
    # Skip messages that already have a row for this label.
    inserted = 0
    if evidence_msg_ids:
        have_res = (
            supabase.table("message_scores")
            .select("msg_id")
            .in_("msg_id", evidence_msg_ids)
            .eq("label", label)
            .execute()
        )
        have = {row["msg_id"] for row in have_res.data}
        rows = [
            {"msg_id": e["message_id"], "label": label, "confidence": e["score"], "source": source}
            for e in evidence
            if e["message_id"] not in have
        ]
        if rows:
            supabase.table("message_scores").insert(rows).execute()
            inserted = len(rows)

    return {"conversation_scores": conversation_status, "message_scores_inserted": inserted}


def score_conversation_request(
    conversation_id: str,
    supabase,
    embed_model,
    model,
    embedding_store,
    model_version: str,
) -> dict:
    messages = fetch_message_window(supabase, conversation_id)
    if not messages:
        return {"conversation_scores": "no_messages", "message_scores_inserted": 0}

    from inference import score_conversation  # pipeline/, on sys.path -- see app/main.py

    messages = embedding_store.get_or_compute(messages, embed_model, model_version)
    # Confirmed past reports ride along as reference patterns on every call
    # (see watchlist_service.py) -- the human-feedback loop's reach beyond
    # the one conversation a report was filed in.
    confirmed_examples = SupabaseWatchlist(supabase).get_confirmed_examples()
    result = score_conversation(conversation_id, messages, model,
                                 confirmed_examples=confirmed_examples)
    return write_scores(supabase, conversation_id, result)
