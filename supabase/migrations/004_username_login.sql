-- 004_username_login.sql
-- Username-or-email login + signup username/phone support.
--
-- 1. profiles.phone — optional Singapore number, display only (no OTP).
-- 2. Case-insensitive unique index on username — login lookup and the
--    availability check both compare lower(username); the plain UNIQUE
--    constraint from 001 is case-sensitive and would allow 'Foo'/'foo'
--    to coexist, making the lookup ambiguous.
-- 3. handle_new_user hardening — lowercase usernames, collision-proof
--    fallback (a duplicate derived username must never abort the
--    auth.users insert), and phone read from signup metadata.
-- 4. get_email_for_username — SECURITY DEFINER resolver so the client
--    never queries auth.users. Returns the email ONLY for an exact
--    (case-insensitive) username match. Granted to anon because login
--    happens pre-auth. Accepted tradeoff: anyone can probe
--    username -> email; fine for this prototype, and a rate-limited
--    server-side sign-in is the later fix if it ever matters.
-- 5. username_exists — signup availability pre-check (boolean only, so
--    it leaks existence but never an email). Without it a duplicate
--    username surfaces as an opaque "Database error saving new user"
--    from the trigger.

-- =====================================================================
-- 1. Display-only optional phone
-- =====================================================================

alter table public.profiles add column if not exists phone text;

-- =====================================================================
-- 2. Case-insensitive username uniqueness
-- =====================================================================

create unique index if not exists profiles_username_lower_idx
  on public.profiles (lower(username));

-- =====================================================================
-- 3. Harden handle_new_user (replaces the 001 version; the
--    on_auth_user_created trigger already points at this function)
-- =====================================================================

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  _username text;
  _base     text;
  _n        int := 1;
begin
  _username := lower(nullif(trim(new.raw_user_meta_data ->> 'username'), ''));
  if _username is null then
    -- Fallback (dashboard-created users etc.): derive from the email
    -- local-part and de-duplicate so a collision never aborts signup.
    _base := lower(split_part(new.email, '@', 1));
    _username := _base;
    while exists (select 1 from public.profiles where lower(username) = _username) loop
      _username := _base || _n::text;
      _n := _n + 1;
    end loop;
  end if;

  insert into public.profiles (id, username, display_name, avatar_color, phone)
  values (
    new.id,
    _username,
    coalesce(new.raw_user_meta_data ->> 'display_name', _username),
    coalesce(new.raw_user_meta_data ->> 'avatar_color', '#64748b'),
    nullif(trim(new.raw_user_meta_data ->> 'phone'), '')
  );
  return new;
end;
$$;

-- =====================================================================
-- 4. Username -> email resolver for login (see header for tradeoff)
-- =====================================================================

create or replace function public.get_email_for_username(_username text)
returns text
language sql
stable
security definer
set search_path = public
as $$
  select u.email
  from public.profiles p
  join auth.users u on u.id = p.id
  where lower(p.username) = lower(trim(_username))
  limit 1;
$$;

revoke all on function public.get_email_for_username(text) from public;
grant execute on function public.get_email_for_username(text) to anon, authenticated;

-- =====================================================================
-- 5. Signup availability pre-check
-- =====================================================================

create or replace function public.username_exists(_username text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.profiles
    where lower(username) = lower(trim(_username))
  );
$$;

revoke all on function public.username_exists(text) from public;
grant execute on function public.username_exists(text) to anon, authenticated;
