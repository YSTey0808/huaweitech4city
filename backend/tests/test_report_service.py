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
    ]
    captured = {}

    def fake_score_conversation(conversation_id, messages, model, user_report=None):
        captured["conversation_id"] = conversation_id
        captured["messages"] = messages
        captured["user_report"] = user_report
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
    assert captured["user_report"] == {"message_id": "m1", "reason": "this looks like a scam"}
    assert captured["messages"][0]["embedding"] == "fake-embedding"  # embedding_store was applied

    assert out["conversation_scores"] == "inserted"
    assert fake_supabase.store["conversation_scores"][0]["source"] == "user_report"
