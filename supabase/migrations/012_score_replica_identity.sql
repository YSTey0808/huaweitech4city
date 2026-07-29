-- 012_score_replica_identity.sql
-- Make flag ANNULMENT visible live. When a false-positive dispute is
-- confirmed, backend report_service._annul_message_flags DELETEs the
-- message_scores / conversation_scores rows, and useScores.ts subscribes to
-- those DELETE events to clear the flag from the UI without a refresh.
--
-- By default Postgres only puts a row's PRIMARY KEY in the logical-replication
-- "old" image for DELETE/UPDATE. Supabase Realtime uses that image both to
-- build the event payload AND to evaluate RLS before delivering it. Both
-- score tables key on `id`, but their RLS SELECT policies filter on other
-- columns -- message_scores on msg_id (via its messages join),
-- conversation_scores on conversation_id -- which aren't in a PK-only image.
-- Realtime therefore cannot authorize the DELETE and silently drops it, so
-- an annulled flag would only disappear on refresh.
--
-- REPLICA IDENTITY FULL includes the whole old row in that image, letting
-- Realtime evaluate the policy and deliver the DELETE. (INSERT/UPDATE were
-- never affected -- they carry the full new row already.)

alter table public.message_scores replica identity full;
alter table public.conversation_scores replica identity full;
