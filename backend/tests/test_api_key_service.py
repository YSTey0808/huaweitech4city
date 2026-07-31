import pytest

from app.services import rate_limiter
from app.services.api_key_service import clear_cache, hash_key, log_usage, verify_api_key


@pytest.fixture(autouse=True)
def _isolate_module_state():
    # Both services hold process-global state; without this, cached keys and
    # hit counters leak between tests.
    clear_cache()
    rate_limiter.reset()
    yield
    clear_cache()
    rate_limiter.reset()


def add_key(fake_supabase, raw_key: str, *, is_active: bool = True, rate_limit: int = 20):
    fake_supabase.store.setdefault("api_keys", []).append({
        "id": f"key-{raw_key}",
        "key_hash": hash_key(raw_key),
        "partner_name": "Acme",
        "is_active": is_active,
        "rate_limit_per_min": rate_limit,
    })


# ---- verify_api_key ----

def test_verify_accepts_active_key(fake_supabase):
    add_key(fake_supabase, "pk_live_good")
    row = verify_api_key(fake_supabase, "pk_live_good")
    assert row is not None
    assert row["partner_name"] == "Acme"


def test_verify_rejects_unknown_key(fake_supabase):
    add_key(fake_supabase, "pk_live_good")
    assert verify_api_key(fake_supabase, "pk_live_nope") is None


def test_verify_rejects_inactive_key(fake_supabase):
    add_key(fake_supabase, "pk_live_revoked", is_active=False)
    assert verify_api_key(fake_supabase, "pk_live_revoked") is None


def test_verify_rejects_empty_key_without_touching_db(fake_supabase):
    assert verify_api_key(fake_supabase, "") is None
    assert "api_keys" not in fake_supabase.store  # no query issued


def test_verify_never_stores_plaintext(fake_supabase):
    add_key(fake_supabase, "pk_live_secret")
    assert fake_supabase.store["api_keys"][0]["key_hash"] != "pk_live_secret"
    assert len(fake_supabase.store["api_keys"][0]["key_hash"]) == 64  # sha256 hex


def test_verify_caches_and_avoids_repeat_lookups(fake_supabase):
    add_key(fake_supabase, "pk_live_good")
    assert verify_api_key(fake_supabase, "pk_live_good") is not None

    # Emptying the table must not affect the cached answer within the TTL.
    fake_supabase.store["api_keys"] = []
    assert verify_api_key(fake_supabase, "pk_live_good") is not None

    clear_cache()
    assert verify_api_key(fake_supabase, "pk_live_good") is None


def test_verify_caches_negative_results(fake_supabase):
    # A client looping with a bad key must not become sustained DB load.
    assert verify_api_key(fake_supabase, "pk_live_bad") is None
    add_key(fake_supabase, "pk_live_bad")
    assert verify_api_key(fake_supabase, "pk_live_bad") is None  # still cached as invalid


def test_verify_fails_closed_when_lookup_raises():
    class BrokenSupabase:
        def table(self, _name):
            raise RuntimeError("supabase down")

    # No safe degraded mode here: the only alternative to rejecting is
    # admitting an unverified caller.
    assert verify_api_key(BrokenSupabase(), "pk_live_good") is None


# ---- rate limiter ----

def test_rate_limit_allows_up_to_the_limit():
    assert all(rate_limiter.check_rate_limit("k1", 3) is None for _ in range(3))


def test_rate_limit_blocks_past_the_limit():
    for _ in range(3):
        rate_limiter.check_rate_limit("k1", 3)
    retry_after = rate_limiter.check_rate_limit("k1", 3)
    assert retry_after is not None
    assert retry_after >= 1  # never advise an immediate retry


def test_rate_limit_is_per_key():
    for _ in range(3):
        rate_limiter.check_rate_limit("k1", 3)
    assert rate_limiter.check_rate_limit("k2", 3) is None


def test_rejected_requests_do_not_count_against_the_window():
    # Otherwise an aggressively retrying client could never recover.
    for _ in range(3):
        rate_limiter.check_rate_limit("k1", 3)
    first = rate_limiter.check_rate_limit("k1", 3)
    for _ in range(20):
        rate_limiter.check_rate_limit("k1", 3)
    assert rate_limiter.check_rate_limit("k1", 3) <= first


# ---- log_usage ----

def test_log_usage_writes_metadata_only(fake_supabase):
    log_usage(fake_supabase, "key-1", message_count=4, verdict_label="harmful", latency_ms=1200)
    row = fake_supabase.store["api_usage"][0]
    assert row["api_key_id"] == "key-1"
    assert row["message_count"] == 4
    assert row["verdict_label"] == "harmful"
    assert row["latency_ms"] == 1200
    # The privacy commitment in docs/public_api.md, asserted.
    assert not {"text", "content", "sender_id", "messages"} & set(row)


def test_log_usage_never_raises():
    class BrokenSupabase:
        def table(self, _name):
            raise RuntimeError("supabase down")

    # Runs after the verdict is already returned; a logging failure must not
    # surface as a failed scoring request.
    log_usage(BrokenSupabase(), "key-1", 1, "safe", 10)
