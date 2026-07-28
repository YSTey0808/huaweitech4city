"""Tests for report_service.py's orchestration. inference.score_conversation
is swapped for a spy via sys.modules -- backend's venv has no torch and
report_service.py imports it lazily (`from inference import score_conversation`
inside the function body) specifically so this works without the pipeline's
heavy deps installed."""

import sys
import types

import pytest

from app.services.report_service import report_message_request


class FakeEmbeddingStore:
    def get_or_compute(self, messages, embed_model, model_version):
        return [{**m, "embedding": "fake-embedding"} for m in messages]


def _install_fake_inference(monkeypatch, fn):
    fake_module = types.ModuleType("inference")
    fake_module.score_conversation = fn
    monkeypatch.setitem(sys.modules, "inference", fake_module)


def test_report_message_request_message_not_found_returns_early(fake_supabase):
    fake_supabase.store["messages"] = []  # anchor lookup finds nothing

    out = report_message_request(
        "c1", "missing-msg", "this is a scam", fake_supabase,
        embed_model=None, model=None, embedding_store=FakeEmbeddingStore(), model_version="v1",
    )

    assert out == {"conversation_scores": "message_not_found", "message_scores_inserted": 0}


def test_report_message_request_rejects_message_from_other_conversation(fake_supabase, monkeypatch):
    fake_supabase.store["messages"] = [
        {"id": "m1", "conversation_id": "OTHER_CONV", "sender_id": "u1", "content": "hi",
         "reply_to": None, "created_at": "2026-07-22T00:00:00+00:00"},
    ]
    called = []
    _install_fake_inference(monkeypatch, lambda *a, **kw: called.append(1) or {})

    out = report_message_request(
        "c1", "m1", "this is a scam", fake_supabase,
        embed_model=None, model=None, embedding_store=FakeEmbeddingStore(), model_version="v1",
    )

    assert out == {"conversation_scores": "message_not_found", "message_scores_inserted": 0}
    assert called == []  # never even attempted to score a mismatched pairing


def test_report_message_request_happy_path(fake_supabase, monkeypatch):
    fake_supabase.store["messages"] = [
        {"id": "m1", "conversation_id": "c1", "sender_id": "u1", "content": "hi",
         "reply_to": None, "created_at": "2026-07-22T00:00:00+00:00"},
        # A previously reported-and-confirmed message from another
        # conversation -- should ride along as a watchlist example.
        {"id": "m0", "conversation_id": "OTHER", "sender_id": "u9", "content": "send otp now",
         "reply_to": None, "created_at": "2026-07-21T00:00:00+00:00"},
    ]
    fake_supabase.store["message_reports"] = [
        {"msg_id": "m0", "reason": "asked for my otp", "status": "confirmed", "claim": "harmful",
         "created_at": "2026-07-21T01:00:00+00:00"},
        # The report being processed by this request (frontend inserted it
        # before invoking the Edge Function) -- must get stamped 'confirmed'.
        {"msg_id": "m1", "conversation_id": "c1", "reason": "this looks like a scam",
         "status": "pending", "claim": "harmful", "created_at": "2026-07-22T00:01:00+00:00"},
    ]
    fake_supabase.store["message_scores"] = [
        {"msg_id": "m0", "label": "scam", "source": "user_report"},
    ]
    captured = {}

    def fake_score_conversation(conversation_id, messages, model, user_report=None,
                                confirmed_examples=None):
        captured["conversation_id"] = conversation_id
        captured["messages"] = messages
        captured["user_report"] = user_report
        captured["confirmed_examples"] = confirmed_examples
        return {
            "conversation_label": "harmful",
            "conversation_confidence": 0.8,
            "severity": "medium",
            "gentle_alert_text": "flagged",
            "top_evidence_messages": [{"message_id": "m1", "score": 0.8}],
        }

    _install_fake_inference(monkeypatch, fake_score_conversation)

    out = report_message_request(
        "c1", "m1", "this looks like a scam", fake_supabase,
        embed_model=None, model="fake-model", embedding_store=FakeEmbeddingStore(), model_version="v1",
    )

    assert captured["conversation_id"] == "c1"
    assert captured["user_report"] == {"message_id": "m1", "reason": "this looks like a scam",
                                        "claim": "harmful"}
    assert captured["messages"][0]["embedding"] == "fake-embedding"  # embedding_store was applied
    assert captured["confirmed_examples"] == [
        {"text": "send otp now", "reason": "asked for my otp", "label": "scam"}
    ]

    assert out["conversation_scores"] == "inserted"
    # conversation_scores store now also holds the pre-seeded message_scores row's
    # sibling insert -- check the conversation-level row specifically.
    assert fake_supabase.store["conversation_scores"][0]["source"] == "user_report"

    # The report row got its outcome stamped (migration 009).
    assert out["report_status"] == "confirmed"
    stamped = next(r for r in fake_supabase.store["message_reports"] if r["msg_id"] == "m1")
    assert stamped["status"] == "confirmed"
    assert stamped["outcome_reasoning"] == "flagged"
    assert stamped["resolved_at"] is not None
    # The unrelated watchlist-source report (other conversation) is untouched
    # by this request's outcome stamp -- it was seeded 'confirmed' already,
    # so the tell is the absence of the stamp's other fields.
    other = next(r for r in fake_supabase.store["message_reports"] if r["msg_id"] == "m0")
    assert "outcome_reasoning" not in other
    assert "resolved_at" not in other


def test_report_message_request_dismissal_stamps_report_and_writes_no_scores(fake_supabase, monkeypatch):
    fake_supabase.store["messages"] = [
        {"id": "m1", "conversation_id": "c1", "sender_id": "u1", "content": "see you at 7",
         "reply_to": None, "created_at": "2026-07-22T00:00:00+00:00"},
    ]
    fake_supabase.store["message_reports"] = [
        {"msg_id": "m1", "conversation_id": "c1", "reason": "im sure this is bad",
         "status": "pending", "created_at": "2026-07-22T00:01:00+00:00"},
    ]

    def fake_score_conversation(conversation_id, messages, model, user_report=None,
                                confirmed_examples=None):
        # The LLM disagrees with the report.
        return {
            "conversation_label": "safe",
            "conversation_confidence": 0.9,
            "severity": None,
            "gentle_alert_text": "This message is an ordinary plan to meet; nothing suggests harm.",
            "top_evidence_messages": [],
        }

    _install_fake_inference(monkeypatch, fake_score_conversation)

    out = report_message_request(
        "c1", "m1", "im sure this is bad", fake_supabase,
        embed_model=None, model="fake-model", embedding_store=FakeEmbeddingStore(), model_version="v1",
    )

    # Absence-of-rows = safe convention holds: nothing written to scores.
    assert out["conversation_scores"] == "safe"
    assert fake_supabase.store.get("conversation_scores", []) == []

    # But the report itself is stamped dismissed, with the LLM's explanation.
    assert out["report_status"] == "dismissed"
    stamped = fake_supabase.store["message_reports"][0]
    assert stamped["status"] == "dismissed"
    assert "ordinary plan to meet" in stamped["outcome_reasoning"]
    assert stamped["resolved_at"] is not None


# ---- claim='safe' (false-positive dispute, migration 010) ----

def _seed_flagged_conversation(fake_supabase):
    """A flagged message m1 in c1: one message_scores row, plus a
    conversation_scores row citing m1 and m2 as evidence."""
    fake_supabase.store["messages"] = [
        {"id": "m1", "conversation_id": "c1", "sender_id": "u1", "content": "eh you free tonight",
         "reply_to": None, "created_at": "2026-07-28T00:00:00+00:00"},
    ]
    fake_supabase.store["message_reports"] = [
        {"msg_id": "m1", "conversation_id": "c1", "reason": "thats just my aunt",
         "status": "pending", "claim": "safe", "created_at": "2026-07-28T00:01:00+00:00"},
    ]
    fake_supabase.store["message_scores"] = [
        {"id": "ms1", "msg_id": "m1", "label": "grooming", "source": "model"},
    ]
    fake_supabase.store["conversation_scores"] = [
        {"id": "cs1", "conversation_id": "c1", "label": "grooming",
         "evidence_msg_ids": ["m1", "m2"], "source": "model"},
    ]


def test_dispute_confirmed_annuls_flags_and_prunes_evidence(fake_supabase, monkeypatch):
    _seed_flagged_conversation(fake_supabase)
    captured = {}

    def fake_score_conversation(conversation_id, messages, model, user_report=None,
                                confirmed_examples=None):
        captured["user_report"] = user_report
        # The LLM agrees the flag was wrong.
        return {
            "conversation_label": "safe",
            "conversation_confidence": 0.95,
            "severity": None,
            "gentle_alert_text": "An ordinary invitation from a family member.",
            "top_evidence_messages": [],
        }

    _install_fake_inference(monkeypatch, fake_score_conversation)

    out = report_message_request(
        "c1", "m1", "thats just my aunt", fake_supabase,
        embed_model=None, model="fake-model", embedding_store=FakeEmbeddingStore(),
        model_version="v1", claim="safe",
    )

    assert captured["user_report"]["claim"] == "safe"
    assert out["conversation_scores"] == "annulled"
    assert out["report_status"] == "confirmed"  # confirmed = LLM agreed with the CLAIM

    # The wrong flag is gone; the conversation row survives with m1 pruned
    # from its evidence (m2 still stands).
    assert fake_supabase.store["message_scores"] == []
    conv_row = fake_supabase.store["conversation_scores"][0]
    assert conv_row["evidence_msg_ids"] == ["m2"]

    stamped = fake_supabase.store["message_reports"][0]
    assert stamped["status"] == "confirmed"
    assert "ordinary invitation" in stamped["outcome_reasoning"]


def test_dispute_confirmed_deletes_conversation_row_when_evidence_empties(fake_supabase, monkeypatch):
    _seed_flagged_conversation(fake_supabase)
    # m1 is the ONLY evidence this time -> annulment must delete the row.
    fake_supabase.store["conversation_scores"][0]["evidence_msg_ids"] = ["m1"]

    _install_fake_inference(monkeypatch, lambda *a, **kw: {
        "conversation_label": "safe", "conversation_confidence": 0.95,
        "severity": None, "gentle_alert_text": "Harmless.", "top_evidence_messages": [],
    })

    report_message_request(
        "c1", "m1", "thats just my aunt", fake_supabase,
        embed_model=None, model="fake-model", embedding_store=FakeEmbeddingStore(),
        model_version="v1", claim="safe",
    )

    assert fake_supabase.store["conversation_scores"] == []


def test_dispute_rejected_leaves_flags_untouched(fake_supabase, monkeypatch):
    _seed_flagged_conversation(fake_supabase)

    _install_fake_inference(monkeypatch, lambda *a, **kw: {
        # The LLM stands by the flag.
        "conversation_label": "harmful", "conversation_confidence": 0.9,
        "severity": "high",
        "gentle_alert_text": "The surrounding messages show escalating pressure to meet alone.",
        "top_evidence_messages": [{"message_id": "m1", "score": 0.9}],
    })

    out = report_message_request(
        "c1", "m1", "thats just my aunt", fake_supabase,
        embed_model=None, model="fake-model", embedding_store=FakeEmbeddingStore(),
        model_version="v1", claim="safe",
    )

    assert out["conversation_scores"] == "flag_stands"
    assert out["report_status"] == "dismissed"  # LLM disagreed with the claim

    # Nothing annulled, nothing re-written: the existing rows are
    # byte-identical, still source='model' (never re-stamped 'user_report').
    assert fake_supabase.store["message_scores"] == [
        {"id": "ms1", "msg_id": "m1", "label": "grooming", "source": "model"},
    ]
    assert fake_supabase.store["conversation_scores"][0]["evidence_msg_ids"] == ["m1", "m2"]
    assert fake_supabase.store["conversation_scores"][0]["source"] == "model"

    stamped = fake_supabase.store["message_reports"][0]
    assert stamped["status"] == "dismissed"
    assert "escalating pressure" in stamped["outcome_reasoning"]
