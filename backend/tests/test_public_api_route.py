"""Route-level tests for POST /v1/analyze.

Builds a bare FastAPI app around the router rather than importing app.main --
main.py loads sentence-transformers and the GNN checkpoint at import time,
which these tests have no need for. The scoring call itself is stubbed; what
is under test here is the gate in front of it (auth, throttle, validation)
and the usage logging behind it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import public_api
from app.services import rate_limiter
from app.services.api_key_service import clear_cache, hash_key

VALID_KEY = "pk_live_test"


@pytest.fixture
def client(fake_supabase, monkeypatch):
    clear_cache()
    rate_limiter.reset()

    fake_supabase.store["api_keys"] = [{
        "id": "key-1",
        "key_hash": hash_key(VALID_KEY),
        "partner_name": "Acme",
        "is_active": True,
        "rate_limit_per_min": 3,
    }]

    monkeypatch.setattr(public_api, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(public_api, "analyze_messages", lambda **kwargs: {
        "conversation_id": kwargs["conversation_id"],
        "conversation_label": "harmful",
        "conversation_confidence": 0.9,
        "severity": "high",
        "top_evidence_messages": [
            {"message_id": "m1", "text": "where do u stay", "score": 0.8, "tags": ["grooming"]}
        ],
        "gentle_alert_text": "heads up",
        "model_version": "test-model",
    })

    app = FastAPI()
    app.include_router(public_api.router)
    # analyze_messages is stubbed, so the real model/embedder are never touched.
    app.state.embed_model = app.state.model = None
    app.state.model_version = "test-model"

    with TestClient(app) as c:
        yield c

    clear_cache()
    rate_limiter.reset()


def body(n: int = 2, **extra):
    return {
        "messages": [
            {"message_id": f"m{i}", "sender_id": f"u{i}", "text": f"t{i}"} for i in range(n)
        ],
        **extra,
    }


def post(client, payload, key=VALID_KEY):
    return client.post("/v1/analyze", json=payload, headers={"X-API-Key": key})


# ---- auth ----

def test_valid_key_returns_verdict(client):
    res = post(client, body(**{"conversation_id": "acme-1"}))
    assert res.status_code == 200
    assert res.json()["conversation_label"] == "harmful"
    assert res.json()["conversation_id"] == "acme-1"
    assert res.json()["model_version"] == "test-model"


def test_missing_key_is_401(client):
    assert client.post("/v1/analyze", json=body()).status_code == 401


def test_wrong_key_is_401(client):
    assert post(client, body(), key="pk_live_wrong").status_code == 401


def test_401_does_not_log_usage(client, fake_supabase):
    post(client, body(), key="pk_live_wrong")
    assert fake_supabase.store.get("api_usage", []) == []


# ---- validation ----

def test_empty_messages_is_422(client):
    assert post(client, {"messages": []}).status_code == 422


def test_oversized_window_is_422(client):
    assert post(client, body(51)).status_code == 422


def test_duplicate_message_ids_is_422(client):
    payload = {"messages": [
        {"message_id": "dup", "sender_id": "u1", "text": "a"},
        {"message_id": "dup", "sender_id": "u2", "text": "b"},
    ]}
    assert post(client, payload).status_code == 422


def test_conversation_id_is_optional(client):
    res = post(client, body())
    assert res.status_code == 200
    assert res.json()["conversation_id"] is None


# ---- rate limiting ----

def test_rate_limit_returns_429_with_retry_after(client):
    for _ in range(3):  # rate_limit_per_min = 3 for this key
        assert post(client, body()).status_code == 200

    res = post(client, body())
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) >= 1


# ---- usage logging ----

def test_success_logs_metadata_only(client, fake_supabase):
    post(client, body(4))
    rows = fake_supabase.store["api_usage"]
    assert len(rows) == 1
    assert rows[0]["api_key_id"] == "key-1"
    assert rows[0]["message_count"] == 4
    assert rows[0]["verdict_label"] == "harmful"
    assert rows[0]["latency_ms"] >= 0
    assert not {"text", "content", "sender_id", "messages"} & set(rows[0])


def test_usage_logging_failure_does_not_fail_the_request(client, fake_supabase, monkeypatch):
    """A broken api_usage insert must not turn an already-computed verdict
    into an error for the partner. Exercises the real log_usage (not a stub),
    so the swallow it promises is actually under test."""
    real_table = fake_supabase.table

    def table(name):
        if name == "api_usage":
            raise RuntimeError("insert failed")
        return real_table(name)

    monkeypatch.setattr(fake_supabase, "table", table)

    res = post(client, body())
    assert res.status_code == 200
    assert res.json()["conversation_label"] == "harmful"
