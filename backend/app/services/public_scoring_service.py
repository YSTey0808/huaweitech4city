"""
Stateless sibling of scoring_service.py, backing the public partner API
(POST /v1/analyze).

scoring_service takes a conversation_id and re-fetches the window from OUR
Supabase, then writes verdict rows the frontend reads over Realtime. A
partner has neither: their messages live in their database and they want the
verdict in the HTTP response. So this module takes the messages inline,
scores them, and returns -- touching no product table on the way in or out.

It reuses the same stage functions as the internal path (embed_conversations,
score_conversation, SupabaseWatchlist), so there is exactly one implementation
of scoring and a partner is never served a different model than our own users.
"""

from .watchlist_service import SupabaseWatchlist

SAFE_LABEL = "safe"  # gnn/config.py's CONV_LABELS is ["safe", "harmful"]


def normalize_partner_messages(messages: list) -> list:
    """Partner dicts -> the pipeline's canonical message shape, the same
    shape message_mapper.supabase_row_to_pipeline_message() produces for our
    own rows.

    The only real work is `timestamp`: build_message_graph() uses it to build
    temporal edges, and it is optional in the partner contract. When it's
    missing we backfill from array position, which preserves the ordering the
    caller already committed to by sending a chronological list. Mixing given
    and backfilled timestamps in one request would produce nonsense edges, so
    it's all-or-nothing: if ANY message omits a timestamp, positions are used
    for every message.
    """
    any_missing = any(m.get("timestamp") is None for m in messages)
    return [
        {
            "message_id": m["message_id"],
            "sender_id": m["sender_id"],
            "text": m.get("text") or "",
            "reply_to_message_id": m.get("reply_to_message_id"),
            "timestamp": float(i) if any_missing else float(m["timestamp"]),
        }
        for i, m in enumerate(messages)
    ]


def build_analyze_response(result: dict, conversation_id: str | None, model_version: str) -> dict:
    """The pipeline verdict -> the published /v1/analyze response shape.

    Evidence for message_ids we were never sent is dropped. The LLM stage is
    told to cite ids from the window, but it is a language model and the
    partner contract promises "your original message_id, unchanged" -- so
    that promise is enforced here rather than trusted. The internal path
    doesn't need this guard: it writes message_scores rows keyed by a
    messages.id foreign key, so an invented id fails at the database instead.
    """
    label = result.get("conversation_label", SAFE_LABEL)
    known_ids = result.get("_known_message_ids")

    evidence = []
    for e in result.get("top_evidence_messages") or []:
        message_id = e.get("message_id")
        if known_ids is not None and message_id not in known_ids:
            print(f"dropping evidence for unknown message_id {message_id!r}")
            continue
        evidence.append({
            "message_id": message_id,
            "text": e.get("text") or "",
            "score": e.get("score") or 0.0,
            "tags": e.get("tags") or [],
        })

    return {
        "conversation_id": conversation_id,
        "conversation_label": label,
        "conversation_confidence": result.get("conversation_confidence") or 0.0,
        # Safe conversations carry no severity/alert -- mirrors write_scores()
        # writing no rows at all in that case (absence = safe).
        "severity": result.get("severity") if label != SAFE_LABEL else None,
        "top_evidence_messages": evidence if label != SAFE_LABEL else [],
        "gentle_alert_text": result.get("gentle_alert_text") if label != SAFE_LABEL else None,
        "model_version": model_version,
    }


def analyze_messages(
    messages: list,
    conversation_id: str | None,
    supabase,
    embed_model,
    model,
    model_version: str,
) -> dict:
    """Full stateless path: normalize -> embed -> GNN + LLM -> response dict."""
    from embed import embed_conversations  # pipeline/, on sys.path -- see app/main.py
    from inference import score_conversation

    normalized = normalize_partner_messages(messages)

    # NOT app.state.embedding_store, deliberately. LocalEmbeddingStore is
    # keyed by (message_id, model_version), and partner message_ids are
    # arbitrary client strings -- "m1", "1", "msg-001" -- which collide
    # across partners and with our own UUIDs. A collision would serve one
    # partner another's cached vector: a silently wrong verdict AND a
    # cross-tenant leak. Embedding fresh every call is the correct trade;
    # over a <=50 message window it's a few hundred ms on CPU and the
    # Anthropic call dominates latency anyway.
    vectors = embed_conversations(
        [{"messages": [{"message_id": m["message_id"], "content": m["text"]} for m in normalized]}],
        embed_model,
    )
    embedded = [{**m, "embedding": vectors[m["message_id"]]} for m in normalized]

    # Partners get the same confirmed-report reference patterns our own
    # scoring uses (watchlist_service.py), so a pattern our users caught
    # improves partner verdicts immediately, before any retrain. Read-only,
    # and the example text reaches the LLM prompt only -- never the response.
    confirmed_examples = SupabaseWatchlist(supabase).get_confirmed_examples()

    result = score_conversation(
        conversation_id or "partner-request",
        embedded,
        model,
        confirmed_examples=confirmed_examples,
    )
    result["_known_message_ids"] = {m["message_id"] for m in normalized}
    return build_analyze_response(result, conversation_id, model_version)
