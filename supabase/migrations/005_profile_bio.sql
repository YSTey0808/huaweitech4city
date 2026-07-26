-- 005_profile_bio.sql
-- Profile editing upgrade: short bio + member-since timestamp.
--
-- 1. profiles.bio — optional short bio, hard-capped at 160 chars so the
--    DB matches the UI counter even if a client bypasses it.
-- 2. profiles.created_at — powers "member since". New rows get now()
--    via the default (handle_new_user doesn't set it, which is ≈ signup
--    time anyway); existing rows are backfilled from auth.users so the
--    date reflects the real signup, not when this migration ran.
--
-- No RLS/realtime changes needed: profiles_update_own already covers new
-- columns, and 003 already publishes profiles updates.

alter table public.profiles
  add column if not exists bio text check (char_length(bio) <= 160);

alter table public.profiles
  add column if not exists created_at timestamptz not null default now();

update public.profiles p
set created_at = u.created_at
from auth.users u
where u.id = p.id;
