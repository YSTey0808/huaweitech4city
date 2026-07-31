"""Partner API key verification and metadata-only usage logging
(migration 013).

Distinct from the X-Backend-Secret check in api/routes/score.py: that is one
global secret shared with our own Edge Functions and carries no caller
identity. These are per-partner credentials -- revocable one at a time,
individually throttled, and attributable in api_usage.
"""

import hashlib
import hmac
import time

# How long a verified key stays cached in-process. The tradeoff: without it,
# every /v1/analyze does a Supabase round-trip before doing any real work;
# with it, flipping is_active=false takes up to this long to take effect.
# 60s is a deliberate pick -- fast enough that revoking a leaked key is a
# minute, not a redeploy, and short enough that nobody reasons about it.
_CACHE_TTL_SECONDS = 60

# raw_key -> (expires_at, key_row | None). Negative results are cached too,
# so a partner looping with a stale key can't turn one bad credential into
# sustained database load.
_cache: dict[str, tuple[float, dict | None]] = {}


def hash_key(raw_key: str) -> str:
    """sha256 hex of the plaintext key -- what api_keys.key_hash stores.
    Shared with scripts/mint_api_key.py so minting and verification can
    never drift apart."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(supabase, raw_key: str) -> dict | None:
    """Returns the api_keys row for a valid, active key, else None.

    Caches for _CACHE_TTL_SECONDS (see above).
    """
    if not raw_key:
        return None

    now = time.monotonic()
    cached = _cache.get(raw_key)
    if cached and cached[0] > now:
        return cached[1]

    key_hash = hash_key(raw_key)
    try:
        res = (
            supabase.table("api_keys")
            .select("id, key_hash, partner_name, is_active, rate_limit_per_min")
            .eq("key_hash", key_hash)
            .eq("is_active", True)
            .execute()
        )
    except Exception as e:
        # Fail CLOSED. Unlike the watchlist (which degrades to "score without
        # examples"), a lookup failure here has no safe degraded mode -- the
        # only alternative to rejecting is admitting an unverified caller.
        print(f"api key lookup failed (request rejected): {e}")
        return None

    row = res.data[0] if res.data else None
    # Constant-time confirmation of the hash the database matched on. The
    # equality above already happened server-side, so this guards the
    # comparison we control rather than the query -- cheap, and it keeps this
    # module from modelling secret comparison with a plain != (which is what
    # routes/score.py:18 does for the shared secret).
    if row is not None and not hmac.compare_digest(row["key_hash"], key_hash):
        row = None

    _cache[raw_key] = (now + _CACHE_TTL_SECONDS, row)
    return row


def clear_cache() -> None:
    """Drops the verification cache. For tests, and for a future admin path
    that wants a revocation to land immediately instead of within the TTL."""
    _cache.clear()


def log_usage(supabase, api_key_id: str, message_count: int,
              verdict_label: str | None, latency_ms: int) -> None:
    """Writes one metadata-only api_usage row -- no message text, no sender
    ids (see migration 013).

    Must never raise: this runs as a background task after the verdict has
    already been returned, and a logging failure must not surface as a failed
    scoring request. Same fail-safe contract as
    watchlist_service.get_confirmed_examples().
    """
    try:
        supabase.table("api_usage").insert({
            "api_key_id": api_key_id,
            "message_count": message_count,
            "verdict_label": verdict_label,
            "latency_ms": latency_ms,
        }).execute()
    except Exception as e:
        print(f"api usage logging failed (request already served): {e}")
