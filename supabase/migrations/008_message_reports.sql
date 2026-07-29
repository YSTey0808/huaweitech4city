-- 008_message_reports.sql
-- Human-feedback loop, storage half: users can report a message they believe
-- is harmful but the model missed. Each report is an immutable log row
-- (no update/delete policies), visible only to its reporter, and doubles as
-- a candidate corrected label for future retraining (see
-- pipeline/scripts/export_reports_for_training.py).
--
-- Also tags the existing score tables with their origin, so a score row
-- produced by the report-triggered re-run (backend POST /report, written with
-- source='user_report') stays distinguishable from an automatic model finding
-- (source='model') -- the audit trail the feedback loop depends on.

create table if not exists public.message_reports (
  id              uuid primary key default gen_random_uuid(),
  msg_id          uuid not null references public.messages (id) on delete cascade,
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  reporter_id     uuid not null references auth.users (id) on delete cascade,
  reason          text not null check (length(trim(reason)) > 0),
  created_at      timestamptz not null default now(),
  -- One report per user per message; re-submitting is a no-op (the client
  -- treats the 23505 as already-reported).
  unique (msg_id, reporter_id)
);

create index if not exists idx_message_reports_conversation
  on public.message_reports (conversation_id);

alter table public.message_reports enable row level security;

-- A report is private to the person who filed it -- never visible to the
-- other conversation member (who may be the reported sender).
create policy message_reports_select_own
  on public.message_reports for select
  to authenticated
  using (reporter_id = auth.uid());

-- File reports only as yourself, only in conversations you belong to.
create policy message_reports_insert_own
  on public.message_reports for insert
  to authenticated
  with check (
    reporter_id = auth.uid()
    and public.is_conversation_member(conversation_id, auth.uid())
  );
-- (No UPDATE/DELETE policies: reports are an immutable log.)

-- Realtime, so a reporter's own "reported" state can update live later
-- (stream is RLS-scoped to the reporter's own rows).
alter publication supabase_realtime add table public.message_reports;

-- ---- score provenance ----
alter table public.conversation_scores add column source text not null default 'model'
  check (source in ('model', 'user_report'));
alter table public.message_scores add column source text not null default 'model'
  check (source in ('model', 'user_report'));
