"""Mint a partner API key for the public /v1/analyze endpoint (migration 013).

The plaintext key is printed ONCE and never stored -- only its sha256 hash
goes into api_keys, so it cannot be recovered afterwards. If a partner loses
it, mint a new one and deactivate the old.

Run from backend/ with the backend .env loaded:

    python scripts/mint_api_key.py --partner "Acme Chat"
    python scripts/mint_api_key.py --partner "Demo Judge" --rate-limit 60

    python scripts/mint_api_key.py --list
    python scripts/mint_api_key.py --revoke <key-id>
"""

import argparse
import secrets
import sys
from pathlib import Path

# backend/ on sys.path so `app.*` resolves the same way it does under
# `uvicorn app.main:app` -- mirrors tests/conftest.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.supabase_client import get_supabase  # noqa: E402
from app.services.api_key_service import hash_key  # noqa: E402

KEY_PREFIX = "pk_live_"


def mint(supabase, partner_name: str, rate_limit: int) -> None:
    # 24 bytes = 192 bits of entropy. Far beyond guessable, which is why
    # api_keys can store a plain sha256 rather than a slow password KDF
    # (see migration 013's note).
    raw_key = KEY_PREFIX + secrets.token_urlsafe(24)

    res = supabase.table("api_keys").insert({
        "key_hash": hash_key(raw_key),
        "partner_name": partner_name,
        "rate_limit_per_min": rate_limit,
    }).execute()

    print(f"\nPartner:    {partner_name}")
    print(f"Key id:     {res.data[0]['id']}")
    print(f"Rate limit: {rate_limit} requests/min")
    print(f"\n  {raw_key}\n")
    print("^ Copy this now. It is not stored and cannot be shown again.\n")


def list_keys(supabase) -> None:
    res = (
        supabase.table("api_keys")
        .select("id, partner_name, is_active, rate_limit_per_min, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    if not res.data:
        print("No API keys yet.")
        return
    for row in res.data:
        status = "active " if row["is_active"] else "revoked"
        print(f"{status}  {row['id']}  {row['partner_name']!r}  "
              f"{row['rate_limit_per_min']}/min  {row['created_at']}")


def revoke(supabase, key_id: str) -> None:
    res = supabase.table("api_keys").update({"is_active": False}).eq("id", key_id).execute()
    if not res.data:
        print(f"No key with id {key_id}.")
        return
    # api_key_service caches verified keys for 60s, so a revoked key can still
    # be accepted until that expires. Say so rather than letting an operator
    # assume the cut-off was instant.
    print(f"Revoked {key_id} ({res.data[0]['partner_name']!r}). "
          f"Takes effect within 60s (verification cache TTL).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--partner", help="Partner name to mint a key for")
    parser.add_argument("--rate-limit", type=int, default=20,
                        help="Requests per minute (default: 20). Each request is one billable LLM call.")
    parser.add_argument("--list", action="store_true", help="List existing keys")
    parser.add_argument("--revoke", metavar="KEY_ID", help="Deactivate a key by id")
    args = parser.parse_args()

    supabase = get_supabase()

    if args.list:
        list_keys(supabase)
    elif args.revoke:
        revoke(supabase, args.revoke)
    elif args.partner:
        mint(supabase, args.partner, args.rate_limit)
    else:
        parser.error("one of --partner, --list or --revoke is required")


if __name__ == "__main__":
    main()
