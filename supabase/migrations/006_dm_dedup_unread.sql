-- 006_dm_dedup_unread.sql
-- Add-friend -> chat flow polish: race-proof DM creation + unread tracking.
--
-- 1. conversations.dm_key — uniqueness guard against duplicate DMs. The old
--    client-side openOrCreateDm was a read-then-create with no constraint, so
--    two simultaneous "open chat" clicks could create two conversations for
--    the same pair. dm_key = least(a,b) || ':' || greatest(a,b) of the two
--    member ids; unique index makes creation race-proof. NULL for groups and
--    for legacy duplicates (only the oldest conversation per pair is
--    backfilled — an empty duplicate disappears from the list on its own; a
--    duplicate that already has messages keeps working, it just stays
--    non-canonical. Acceptable prototype residue).
-- 2. open_dm(other_user) — atomic find-or-create RPC, replacing the client's
--    fragile 3-step insert (client-generated id + ordered membership inserts
--    existed only to dodge RLS on INSERT..RETURNING; SECURITY DEFINER makes
--    all of that unnecessary).
-- 3. conversation_members.last_read_at — powers the unread dot in the
--    conversation list. Existing rows default to now() (start "read").
--    New UPDATE policy: users may touch only their own row, and WITH CHECK
--    also re-verifies membership of the (new) conversation_id so the policy
--    can't be used to self-grant membership to an arbitrary conversation.
-- 4. get_dm_overview() — one-shot conversation list (other member, last
--    message, my last_read_at). profiles/members FK auth.users so PostgREST
--    can't embed the join, and "last message per conversation" needs a
--    lateral — this replaces a 4-query client-side dance.
--
-- No realtime publication changes needed: messages (001) and
-- conversation_members (003) are already published.

-- 1. DM dedup key ------------------------------------------------------------

alter table public.conversations
  add column if not exists dm_key text;

create unique index if not exists idx_conversations_dm_key
  on public.conversations (dm_key);

-- Backfill: canonical (oldest) conversation per 2-member DM pair only.
-- Idempotent: already-keyed rows are excluded by "dm_key is null".
with pairs as (
  select cm.conversation_id,
         min(cm.user_id::text) || ':' || max(cm.user_id::text) as key
  from public.conversation_members cm
  join public.conversations c on c.id = cm.conversation_id and not c.is_group
  group by cm.conversation_id
  having count(*) = 2
),
canonical as (
  select distinct on (p.key) p.conversation_id, p.key
  from pairs p
  join public.conversations c on c.id = p.conversation_id
  order by p.key, c.created_at
)
update public.conversations c
set dm_key = canonical.key
from canonical
where c.id = canonical.conversation_id
  and c.dm_key is null;

-- 2. Atomic find-or-create ---------------------------------------------------

create or replace function public.open_dm(other_user uuid)
returns uuid
language plpgsql
volatile
security definer
set search_path = public
as $$
declare
  me   uuid := auth.uid();
  conv uuid;
  key  text;
begin
  if me is null then
    raise exception 'not authenticated';
  end if;
  if other_user is null or other_user = me then
    raise exception 'invalid target user';
  end if;
  -- Friendships are stored as two rows (both directions), so checking one
  -- direction is sufficient.
  if not exists (
    select 1 from public.friendships
    where user_id = me and friend_id = other_user
  ) then
    raise exception 'you are not friends with this user';
  end if;

  key := least(me::text, other_user::text) || ':' ||
         greatest(me::text, other_user::text);

  -- The no-op DO UPDATE makes RETURNING yield the existing row on conflict,
  -- so concurrent callers all resolve to the same conversation id.
  insert into public.conversations (is_group, dm_key)
  values (false, key)
  on conflict (dm_key) do update set dm_key = excluded.dm_key
  returning id into conv;

  insert into public.conversation_members (conversation_id, user_id)
  values (conv, me), (conv, other_user)
  on conflict do nothing;

  return conv;
end;
$$;

revoke all on function public.open_dm(uuid) from public, anon;
grant execute on function public.open_dm(uuid) to authenticated;

-- 3. Unread tracking ---------------------------------------------------------

alter table public.conversation_members
  add column if not exists last_read_at timestamptz not null default now();

-- No UPDATE policy existed. WITH CHECK must keep BOTH arms: without the
-- is_conversation_member re-check, a user could UPDATE their row's
-- conversation_id and self-grant membership to any conversation. (The
-- subquery inside the helper cannot see the in-flight updated row — a
-- command's own changes are invisible to itself — so moving the row to a
-- conversation you're not already in fails the check.)
drop policy if exists conversation_members_update_own on public.conversation_members;
create policy conversation_members_update_own
  on public.conversation_members
  for update
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and public.is_conversation_member(conversation_id, auth.uid())
  );

-- 4. Conversation list overview ----------------------------------------------

create or replace function public.get_dm_overview()
returns table (
  conversation_id uuid,
  other_user_id   uuid,
  last_message_at timestamptz,
  last_sender_id  uuid,
  last_read_at    timestamptz
)
language sql
stable
security definer
set search_path = public
as $$
  select c.id, other.user_id, lm.created_at, lm.sender_id, me.last_read_at
  from public.conversations c
  join public.conversation_members me
    on me.conversation_id = c.id and me.user_id = auth.uid()
  join public.conversation_members other
    on other.conversation_id = c.id and other.user_id <> auth.uid()
  left join lateral (
    select m.created_at, m.sender_id
    from public.messages m
    where m.conversation_id = c.id
    order by m.created_at desc
    limit 1
  ) lm on true
  where not c.is_group;
$$;

revoke all on function public.get_dm_overview() from public, anon;
grant execute on function public.get_dm_overview() to authenticated;
