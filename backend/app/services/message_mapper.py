"""Translates Supabase's live `messages` schema to the pipeline's canonical
message shape -- the field-name/units drift already flagged in the old
huaweitech4city/PROJECT_CONTEXT.md (see docs/data_schema.md):

    Supabase (messages table)      Pipeline canonical field
    --------------------------     ------------------------
    id                             message_id
    content                        text
    reply_to                       reply_to_message_id
    created_at (timestamptz ISO)   timestamp (epoch seconds)
    sender_id                      sender_id (unchanged)

Embeddings are NOT attached here -- that's embedding_store.get_or_compute()'s
job, called separately by scoring_service.py.
"""

from datetime import datetime


def supabase_row_to_pipeline_message(row: dict) -> dict:
    created_at = row.get("created_at")
    timestamp = None
    if created_at:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()

    return {
        "message_id": row["id"],
        "sender_id": row["sender_id"],
        "text": row.get("content") or "",
        "reply_to_message_id": row.get("reply_to"),
        "timestamp": timestamp,
    }
