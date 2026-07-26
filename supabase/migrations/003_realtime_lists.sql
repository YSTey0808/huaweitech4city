-- Realtime for the friends and conversation lists.
-- 001_init.sql only published messages/message_scores/conversation_scores;
-- these tables must be in the publication for their subscriptions to
-- receive events. RLS still applies: realtime only delivers rows the
-- subscriber's SELECT policy allows.
-- (conversations itself is not needed: the lists key off the member row,
-- which is also what grants RLS visibility.)

alter publication supabase_realtime add table public.friendships;
alter publication supabase_realtime add table public.profiles;
alter publication supabase_realtime add table public.conversation_members;
