import sys
from types import ModuleType

import pytest
from pydantic import ValidationError

from app.schemas.public_api import MAX_PARTNER_WINDOW, AnalyzeRequest
from app.services.public_scoring_service import (
    analyze_messages,
    build_analyze_response,
    normalize_partner_messages,
)


def partner_messages(n: int, with_timestamps: bool = True):
    return [
        {
            "message_id": f"m{i}", "sender_id": "u1", "text": f"t{i}",
            "reply_to_message_id": None,
            "timestamp": 1700000000.0 + i if with_timestamps else None,
        }
        for i in range(n)
    ]


# ---- request validation ----

def test_request_rejects_empty_messages():
    with pytest.raises(ValidationError, match="must not be empty"):
        AnalyzeRequest(messages=[])


def test_request_rejects_oversized_window():
    with pytest.raises(ValidationError, match="at most"):
        AnalyzeRequest(messages=partner_messages(MAX_PARTNER_WINDOW + 1))


def test_request_accepts_window_at_the_cap():
    assert len(AnalyzeRequest(messages=partner_messages(MAX_PARTNER_WINDOW)).messages) == MAX_PARTNER_WINDOW


def test_request_rejects_duplicate_message_ids():
    # embed_conversations() returns a message_id -> vector dict, so duplicates
    # would silently collapse into one node.
    dupes = partner_messages(2)
    dupes[1]["message_id"] = dupes[0]["message_id"]
    with pytest.raises(ValidationError, match="unique"):
        AnalyzeRequest(messages=dupes)


def test_request_conversation_id_is_optional():
    assert AnalyzeRequest(messages=partner_messages(1)).conversation_id is None


# ---- normalize_partner_messages ----

def test_normalize_preserves_supplied_timestamps():
    out = normalize_partner_messages(partner_messages(3))
    assert [m["timestamp"] for m in out] == [1700000000.0, 1700000001.0, 1700000002.0]


def test_normalize_backfills_missing_timestamps_from_position():
    out = normalize_partner_messages(partner_messages(3, with_timestamps=False))
    assert [m["timestamp"] for m in out] == [0.0, 1.0, 2.0]


def test_normalize_backfill_is_all_or_nothing():
    # One missing timestamp means positions are used for EVERY message --
    # mixing real epochs with positions would build nonsense temporal edges.
    messages = partner_messages(3)
    messages[1]["timestamp"] = None
    out = normalize_partner_messages(messages)
    assert [m["timestamp"] for m in out] == [0.0, 1.0, 2.0]


def test_normalize_maps_to_canonical_pipeline_shape():
    out = normalize_partner_messages([{
        "message_id": "a", "sender_id": "u9", "text": "hi",
        "reply_to_message_id": "b", "timestamp": 5.0,
    }])
    assert out[0] == {
        "message_id": "a", "sender_id": "u9", "text": "hi",
        "reply_to_message_id": "b", "timestamp": 5.0,
    }


def test_normalize_defaults_missing_text_to_empty_string():
    assert normalize_partner_messages([
        {"message_id": "a", "sender_id": "u1", "text": None, "timestamp": 1.0}
    ])[0]["text"] == ""


# ---- build_analyze_response ----

def _harmful(**overrides):
    result = {
        "conversation_label": "harmful",
        "conversation_confidence": 0.87,
        "severity": "high",
        "gentle_alert_text": "Someone is asking where you live.",
        "top_evidence_messages": [
            {"message_id": "m1", "text": "where do u stay", "score": 0.91, "tags": ["grooming"]}
        ],
        "_known_message_ids": {"m0", "m1"},
    }
    result.update(overrides)
    return result


def test_response_passes_through_harmful_verdict():
    out = build_analyze_response(_harmful(), "acme-1", "model-v1")
    assert out["conversation_id"] == "acme-1"
    assert out["conversation_label"] == "harmful"
    assert out["conversation_confidence"] == 0.87
    assert out["severity"] == "high"
    assert out["model_version"] == "model-v1"
    assert out["top_evidence_messages"][0]["tags"] == ["grooming"]


def test_response_safe_carries_no_severity_evidence_or_alert():
    # Mirrors write_scores(): absence is how "safe" is represented.
    out = build_analyze_response(
        {"conversation_label": "safe", "conversation_confidence": 0.99},
        None, "model-v1",
    )
    assert out["severity"] is None
    assert out["top_evidence_messages"] == []
    assert out["gentle_alert_text"] is None


def test_response_drops_evidence_for_message_ids_we_never_received():
    # The LLM is told to cite ids from the window, but the partner contract
    # promises their own ids back unchanged -- enforce, don't trust.
    result = _harmful(top_evidence_messages=[
        {"message_id": "m1", "text": "real", "score": 0.9, "tags": []},
        {"message_id": "hallucinated", "text": "invented", "score": 0.8, "tags": []},
    ])
    out = build_analyze_response(result, None, "model-v1")
    assert [e["message_id"] for e in out["top_evidence_messages"]] == ["m1"]


def test_response_tolerates_evidence_missing_tags():
    result = _harmful(top_evidence_messages=[{"message_id": "m1", "text": "x", "score": 0.5}])
    assert build_analyze_response(result, None, "v")["top_evidence_messages"][0]["tags"] == []


def test_response_conversation_id_echoed_untouched():
    assert build_analyze_response(_harmful(), "  weird/id?1 ", "v")["conversation_id"] == "  weird/id?1 "


# ---- analyze_messages (orchestration) ----

@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stands in for the two pipeline modules analyze_messages imports lazily
    (`embed` and `inference`, loaded from pipeline/ via sys.path in
    app/main.py). Records the arguments they were called with, so a wrong
    call shape fails here instead of only in production."""
    calls = {}

    def embed_conversations(conversations, model, batch_size=32):
        calls["embed"] = {"conversations": conversations, "model": model}
        return {
            m["message_id"]: f"vec:{m['content']}"
            for conv in conversations for m in conv["messages"]
        }

    def score_conversation(conversation_id, messages, model, user_report=None, confirmed_examples=None):
        calls["score"] = {
            "conversation_id": conversation_id, "messages": messages,
            "model": model, "confirmed_examples": confirmed_examples,
        }
        return {
            "conversation_label": "harmful",
            "conversation_confidence": 0.8,
            "severity": "medium",
            "gentle_alert_text": "heads up",
            "top_evidence_messages": [{"message_id": "m1", "text": "t1", "score": 0.7, "tags": ["scam"]}],
        }

    embed_mod = ModuleType("embed")
    embed_mod.embed_conversations = embed_conversations
    inference_mod = ModuleType("inference")
    inference_mod.score_conversation = score_conversation
    monkeypatch.setitem(sys.modules, "embed", embed_mod)
    monkeypatch.setitem(sys.modules, "inference", inference_mod)
    return calls


def _analyze(fake_supabase, messages, conversation_id="acme-1"):
    return analyze_messages(
        messages=messages, conversation_id=conversation_id, supabase=fake_supabase,
        embed_model="EMBED", model="GNN", model_version="test-model",
    )


def test_analyze_returns_the_published_response_shape(fake_supabase, stub_pipeline):
    out = _analyze(fake_supabase, partner_messages(2))
    assert out == {
        "conversation_id": "acme-1",
        "conversation_label": "harmful",
        "conversation_confidence": 0.8,
        "severity": "medium",
        "top_evidence_messages": [
            {"message_id": "m1", "text": "t1", "score": 0.7, "tags": ["scam"]}
        ],
        "gentle_alert_text": "heads up",
        "model_version": "test-model",
    }


def test_analyze_calls_embed_with_the_shape_embed_conversations_expects(fake_supabase, stub_pipeline):
    _analyze(fake_supabase, partner_messages(2))
    # embed_conversations takes [{"messages": [{"message_id", "content"}]}]
    # -- note "content", not "text". Getting this wrong is a KeyError only at
    # runtime, so pin it.
    assert stub_pipeline["embed"]["conversations"] == [
        {"messages": [{"message_id": "m0", "content": "t0"},
                      {"message_id": "m1", "content": "t1"}]}
    ]
    assert stub_pipeline["embed"]["model"] == "EMBED"


def test_analyze_attaches_embeddings_to_every_message(fake_supabase, stub_pipeline):
    _analyze(fake_supabase, partner_messages(3))
    scored = stub_pipeline["score"]["messages"]
    assert [m["embedding"] for m in scored] == ["vec:t0", "vec:t1", "vec:t2"]


def test_analyze_passes_the_watchlist_through(fake_supabase, stub_pipeline):
    # Partners get the same confirmed-report reference patterns our own users
    # generate -- the cross-network half of the pitch.
    fake_supabase.store["message_reports"] = [
        {"msg_id": "x1", "reason": "asking for bank details", "claim": "harmful",
         "status": "confirmed", "created_at": "2026-07-01T00:00:00+00:00"}
    ]
    fake_supabase.store["message_scores"] = [
        {"msg_id": "x1", "label": "scam", "source": "user_report"}
    ]
    fake_supabase.store["messages"] = [{"id": "x1", "content": "send me your OTP"}]

    _analyze(fake_supabase, partner_messages(1))
    assert stub_pipeline["score"]["confirmed_examples"] == [
        {"text": "send me your OTP", "reason": "asking for bank details", "label": "scam"}
    ]


def test_analyze_writes_nothing_to_product_tables(fake_supabase, stub_pipeline):
    _analyze(fake_supabase, partner_messages(2))
    # A harmful verdict on the internal path would upsert both of these.
    assert fake_supabase.store.get("conversation_scores", []) == []
    assert fake_supabase.store.get("message_scores", []) == []


def test_analyze_tolerates_a_missing_conversation_id(fake_supabase, stub_pipeline):
    out = _analyze(fake_supabase, partner_messages(1), conversation_id=None)
    assert out["conversation_id"] is None
    # score_conversation still needs a non-empty id for its prompt/logging.
    assert stub_pipeline["score"]["conversation_id"]
