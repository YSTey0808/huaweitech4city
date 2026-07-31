"""Per-API-key request throttle for the public partner API.

This is a cost control first and an abuse control second. Every /v1/analyze
call is one billable Anthropic call -- pipeline/inference.py deliberately has
no low-score short-circuit, so there is no such thing as a cheap request.
Without this, a partner's retry loop is an unbounded bill.

Scope: in-process, per uvicorn worker, and it resets on restart. That is
correct for today's deploy -- a single uvicorn process on one VM
(deploy/backend.service) -- and it is the same single-instance assumption
LocalEmbeddingStore already makes (docs/backend.md, "Graph storage &
lifecycle"). If the backend is ever scaled horizontally, the effective limit
becomes rate_limit_per_min * worker_count and this needs to move to Redis or
Postgres. Deliberately no new dependency (slowapi et al.) for a counter this
small.
"""

import time
from collections import deque

WINDOW_SECONDS = 60

# api_key_id -> deque of monotonic timestamps within the trailing window.
_hits: dict[str, deque] = {}


def check_rate_limit(api_key_id: str, limit_per_min: int) -> int | None:
    """Records a hit and returns None if the caller is within their limit.

    When over, returns the number of seconds until the oldest hit falls out
    of the window -- the value to put in Retry-After -- and does NOT record
    the hit (a rejected request costs us nothing, so it must not push the
    caller's own recovery further away; otherwise a client that retries
    aggressively could never get back in).

    A true sliding window rather than fixed buckets: with per-minute buckets
    a partner can send 2x the limit across a bucket boundary, which for an
    LLM-backed endpoint is a real cost spike, not a rounding error.
    """
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS

    hits = _hits.setdefault(api_key_id, deque())
    while hits and hits[0] <= cutoff:
        hits.popleft()

    if len(hits) >= limit_per_min:
        retry_after = WINDOW_SECONDS - (now - hits[0])
        return max(1, int(retry_after) + 1)  # always >= 1s; never advise an immediate retry

    hits.append(now)
    return None


def reset() -> None:
    """Clears all counters. For tests."""
    _hits.clear()
