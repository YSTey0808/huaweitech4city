-- 014_reply_to_reference_integrity.sql
-- messages.reply_to has existed since 001 but was never written by the app --
-- the frontend hardcoded null. Now that the chat UI actually sets it, the
-- column needs the integrity guarantees 001 never had to provide.
--
-- The gap: messages_insert_member (001) checks only `sender_id = auth.uid()`
-- and conversation membership. Nothing constrains reply_to, so a hand-crafted
-- PostgREST insert can point it at ANY message id the caller happens to know,
-- including one belonging to a conversation they are not a member of. The
-- foreign key only proves the row exists, not that it belongs here. A client
-- rendering a reply quote would then try to resolve a parent from another
-- conversation (RLS would hide the text, but the reference itself is still a
-- cross-conversation link we never want written).
--
-- Two guards, both enforced at INSERT:
--   1. a CHECK for the degenerate self-reply, which needs no lookup
--   2. a trigger for the cross-conversation case, which does
-- INSERT-only is sufficient: 001 leaves messages without an UPDATE or DELETE
-- policy on purpose ("messages are immutable in the prototype"), and no
-- server-side code inserts into messages -- the backend only ever reads it.
--
-- Deliberately NOT enforced: parent.created_at < child.created_at. It is true
-- in practice for client inserts, and gnn/conversation_gnn.py's graph builder
-- assumes edges point earlier -> later, but created_at defaults to now()
-- (transaction start time), so two rows can legitimately tie and a strict
-- comparison would reject a valid reply. Raised with the model owner instead.

-- A message cannot reply to itself. Table-level CHECK so it can reference both
-- columns; no lookup required, so this stays a pure constraint.
alter table public.messages
  add constraint messages_reply_to_not_self
  check (reply_to is null or reply_to <> id);

-- The parent must exist AND live in the same conversation as the reply.
-- SECURITY DEFINER so the lookup sees the real row rather than an RLS-filtered
-- one: without it, a parent in someone else's conversation would simply be
-- invisible here and the error would misleadingly read "does not exist".
create or replace function public.validate_message_reply_to()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  parent_conversation_id uuid;
begin
  if new.reply_to is null then
    return new;
  end if;

  select conversation_id into parent_conversation_id
  from public.messages
  where id = new.reply_to;

  if parent_conversation_id is null then
    raise exception 'reply_to references a message that does not exist: %', new.reply_to
      using errcode = 'foreign_key_violation';
  end if;

  if parent_conversation_id <> new.conversation_id then
    raise exception 'reply_to must reference a message in the same conversation'
      using errcode = 'check_violation';
  end if;

  return new;
end;
$$;

drop trigger if exists messages_validate_reply_to on public.messages;
create trigger messages_validate_reply_to
  before insert on public.messages
  for each row execute function public.validate_message_reply_to();

-- Not for an application query -- the client resolves parents by primary key.
-- This exists because reply_to is a self-referencing FK with ON DELETE SET
-- NULL: deleting a message makes Postgres look for children pointing at it,
-- and conversations cascade-delete their messages, so an unindexed reply_to
-- turns one conversation deletion into a sequential scan per message.
-- Partial, since the overwhelming majority of rows have reply_to null.
create index if not exists idx_messages_reply_to
  on public.messages (reply_to)
  where reply_to is not null;
