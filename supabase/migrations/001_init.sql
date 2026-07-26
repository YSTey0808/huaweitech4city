-- 001_init.sql
-- Initial schema for the harm-detection chat prototype.
-- Contract-aligned with CLAUDE.md's Database section. Do not simplify.
--
-- Contents:
--   1. Extensions
--   2. Tables (profiles, friendships, conversations, conversation_members,
--      messages, message_scores, conversation_scores) + indexes
--   3. is_conversation_member() SECURITY DEFINER helper (breaks RLS recursion)
--   4. handle_new_user() signup trigger -> creates a profiles row
--   5. RLS enable + policies
--   6. Realtime publication for messages + score tables

-- =====================================================================
-- 1. Extensions
-- =====================================================================

create extension if not exists pgcrypto;  -- gen_random_uuid()

-- =====================================================================
-- 2. Tables
-- =====================================================================

-- One row per user; mirrors auth.users. Created automatically on signup
-- by the handle_new_user() trigger below.
create table if not exists public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  username     text unique,
  display_name text,
  avatar_color text
);

-- Minimal friendship model: a friendship is stored as two rows
-- (me -> friend and friend -> me). No request/accept flow at this stage.
create table if not exists public.friendships (
  user_id    uuid not null references auth.users (id) on delete cascade,
  friend_id  uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, friend_id)
);

-- conversations.id also serves as the model contract's conversation_id.
create table if not exists public.conversations (
  id         uuid primary key default gen_random_uuid(),
  is_group   boolean not null default false,
  created_at timestamptz not null default now()
);

-- Membership is the single access gate for all conversation data.
create table if not exists public.conversation_members (
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  user_id         uuid not null references auth.users (id) on delete cascade,
  primary key (conversation_id, user_id)
);

-- Prototype is text-only; msg_type and reply_to exist so the schema matches
-- the model contract and never needs rebuilding. receiver_id is NOT stored
-- (derived: the other DM member).
create table if not exists public.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  sender_id       uuid not null references auth.users (id) on delete cascade,
  content         text,
  msg_type        text not null default 'text',
  reply_to        uuid references public.messages (id) on delete set null,
  created_at      timestamptz not null default now()
);

-- Per-message harm scores. Absence of a row = safe. Written only by the
-- score-message Edge Function (service role); clients read but never write.
create table if not exists public.message_scores (
  id         uuid primary key default gen_random_uuid(),
  msg_id     uuid not null references public.messages (id) on delete cascade,
  label      text,
  confidence double precision,
  created_at timestamptz not null default now()
);

-- Conversation-level harm scores. evidence_msg_ids lists the messages that
-- triggered the finding. Absence of rows = safe. Written only server-side.
create table if not exists public.conversation_scores (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null references public.conversations (id) on delete cascade,
  label            text,
  confidence       double precision,
  evidence_msg_ids uuid[],
  created_at       timestamptz not null default now()
);

-- Indexes for the common access paths.
create index if not exists idx_messages_conversation_created
  on public.messages (conversation_id, created_at);
create index if not exists idx_conversation_members_user
  on public.conversation_members (user_id);
create index if not exists idx_message_scores_msg
  on public.message_scores (msg_id);
create index if not exists idx_conversation_scores_conversation
  on public.conversation_scores (conversation_id);

-- =====================================================================
-- 3. Membership helper (SECURITY DEFINER)
-- =====================================================================
-- RLS policies on conversation-scoped tables need to check "is the current
-- user a member of this conversation?". If a policy ON conversation_members
-- queried conversation_members directly, RLS would re-apply to that inner
-- query and recurse infinitely. A SECURITY DEFINER function runs with the
-- owner's rights and bypasses RLS for its internal read, breaking the loop.

create or replace function public.is_conversation_member(
  _conversation_id uuid,
  _user_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.conversation_members cm
    where cm.conversation_id = _conversation_id
      and cm.user_id = _user_id
  );
$$;

-- =====================================================================
-- 4. Signup trigger -> create profiles row
-- =====================================================================

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, username, display_name, avatar_color)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'username',     split_part(new.email, '@', 1)),
    coalesce(new.raw_user_meta_data ->> 'display_name', split_part(new.email, '@', 1)),
    coalesce(new.raw_user_meta_data ->> 'avatar_color', '#64748b')
  );
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- =====================================================================
-- 5. Row Level Security
-- =====================================================================

alter table public.profiles             enable row level security;
alter table public.friendships          enable row level security;
alter table public.conversations        enable row level security;
alter table public.conversation_members enable row level security;
alter table public.messages             enable row level security;
alter table public.message_scores       enable row level security;
alter table public.conversation_scores  enable row level security;

-- ---- profiles ----
-- Any logged-in user can read any profile (needed to find a friend by
-- username/email and to render names/colours in chat).
create policy profiles_select_all
  on public.profiles for select
  to authenticated
  using (true);

-- You may only edit your own profile.
create policy profiles_update_own
  on public.profiles for update
  to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

-- Fallback self-insert; the signup trigger normally creates this row.
create policy profiles_insert_own
  on public.profiles for insert
  to authenticated
  with check (id = auth.uid());

-- ---- friendships ----
-- You can see, create, and delete friendship rows that involve you. The
-- "OR friend_id = auth.uid()" arm lets the two-row insert (both directions)
-- succeed and lets an unfriend remove both rows.
create policy friendships_select_involved
  on public.friendships for select
  to authenticated
  using (user_id = auth.uid() or friend_id = auth.uid());

create policy friendships_insert_involved
  on public.friendships for insert
  to authenticated
  with check (user_id = auth.uid() or friend_id = auth.uid());

create policy friendships_delete_involved
  on public.friendships for delete
  to authenticated
  using (user_id = auth.uid() or friend_id = auth.uid());

-- ---- conversations ----
-- Read only conversations you belong to.
create policy conversations_select_member
  on public.conversations for select
  to authenticated
  using (public.is_conversation_member(id, auth.uid()));

-- Any authenticated user can create a conversation; membership is added
-- separately via conversation_members.
create policy conversations_insert_authenticated
  on public.conversations for insert
  to authenticated
  with check (auth.uid() is not null);

-- ---- conversation_members ----
-- See the member list of conversations you're in (helper avoids recursion).
create policy conversation_members_select_member
  on public.conversation_members for select
  to authenticated
  using (public.is_conversation_member(conversation_id, auth.uid()));

-- Insert allowed when adding yourself (bootstraps a brand-new conversation)
-- or when you are already a member (lets you add the other DM participant).
create policy conversation_members_insert_bootstrap
  on public.conversation_members for insert
  to authenticated
  with check (
    user_id = auth.uid()
    or public.is_conversation_member(conversation_id, auth.uid())
  );

-- ---- messages ----
-- Read messages only in conversations you belong to.
create policy messages_select_member
  on public.messages for select
  to authenticated
  using (public.is_conversation_member(conversation_id, auth.uid()));

-- Post only as yourself, and only into a conversation you belong to.
create policy messages_insert_member
  on public.messages for insert
  to authenticated
  with check (
    sender_id = auth.uid()
    and public.is_conversation_member(conversation_id, auth.uid())
  );
-- (No UPDATE/DELETE policy: messages are immutable in the prototype.)

-- ---- message_scores ----
-- Read a score if you're a member of the conversation its message belongs to.
-- No write policy: only the score-message Edge Function (service role, which
-- bypasses RLS) writes these, so clients can never fabricate alerts.
create policy message_scores_select_member
  on public.message_scores for select
  to authenticated
  using (
    exists (
      select 1
      from public.messages m
      where m.id = msg_id
        and public.is_conversation_member(m.conversation_id, auth.uid())
    )
  );

-- ---- conversation_scores ----
-- Read only for members of the scored conversation. No write policy: only the
-- service-role Edge Function writes (absence of rows = safe).
create policy conversation_scores_select_member
  on public.conversation_scores for select
  to authenticated
  using (public.is_conversation_member(conversation_id, auth.uid()));

-- =====================================================================
-- 6. Realtime
-- =====================================================================
-- Enable change streaming on the tables the UI subscribes to.

alter publication supabase_realtime add table public.messages;
alter publication supabase_realtime add table public.message_scores;
alter publication supabase_realtime add table public.conversation_scores;
