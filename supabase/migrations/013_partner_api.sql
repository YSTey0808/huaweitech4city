-- 013_partner_api.sql
-- Public partner API (POST /v1/analyze): lets another company keep their own
-- chat stack and call our model over HTTP, sending their conversation inline
-- and getting the verdict back in the response body. See docs/public_api.md.
--
-- Two tables, both SERVICE-ROLE ONLY. RLS is enabled with deliberately NO
-- policies -- under Postgres RLS "enabled but no policy" denies every row to
-- anon and authenticated, while the service-role key (which the backend uses,
-- see backend/app/core/supabase_client.py) bypasses RLS entirely. That is
-- exactly the access shape we want: no browser client, ours or a partner's,
-- can ever read a key hash or another partner's usage.

-- ---------------------------------------------------------------------------
-- api_keys: one row per partner integration.
-- ---------------------------------------------------------------------------
-- Only the sha256 hash of the key is stored, never the plaintext -- the
-- plaintext is shown once by backend/scripts/mint_api_key.py and then
-- unrecoverable, so a leak of this table cannot be replayed as valid keys.
-- (sha256 without a slow KDF is appropriate here and NOT the password case:
-- these are 192-bit random tokens, not human-chosen secrets, so there is no
-- guessable keyspace for an attacker to grind against.)
create table public.api_keys (
  id                 uuid primary key default gen_random_uuid(),
  key_hash           text not null unique,
  partner_name       text not null check (length(trim(partner_name)) > 0),
  is_active          boolean not null default true,
  -- Per-key throttle. Every /v1/analyze call is one billable Anthropic call
  -- (pipeline/inference.py never short-circuits the LLM stage), so this is a
  -- cost control as much as an abuse control. Enforced in
  -- backend/app/services/rate_limiter.py.
  rate_limit_per_min integer not null default 20 check (rate_limit_per_min > 0),
  created_at         timestamptz not null default now()
);

-- Verification looks up by hash on (almost) every request; the unique
-- constraint above already provides the index, is_active is checked in the
-- same predicate.
create index api_keys_active_idx on public.api_keys (key_hash) where is_active;

alter table public.api_keys enable row level security;
-- No policies, on purpose. See the header note.

-- ---------------------------------------------------------------------------
-- api_usage: metadata-only call log.
-- ---------------------------------------------------------------------------
-- METADATA ONLY -- deliberately no message text and no sender ids. Partner
-- traffic is scored in memory and discarded (see
-- backend/app/services/public_scoring_service.py, which writes nothing to
-- conversation_scores / message_scores either). That restraint is a product
-- commitment we make to partners in docs/public_api.md, not an oversight:
-- adding a message-text column here would quietly turn us into a processor of
-- their users' content. Don't.
create table public.api_usage (
  id            uuid primary key default gen_random_uuid(),
  api_key_id    uuid not null references public.api_keys(id) on delete cascade,
  called_at     timestamptz not null default now(),
  message_count integer,
  verdict_label text,
  latency_ms    integer
);

create index api_usage_key_time_idx on public.api_usage (api_key_id, called_at desc);

alter table public.api_usage enable row level security;
-- No policies, on purpose. See the header note.
