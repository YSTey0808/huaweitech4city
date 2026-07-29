-- 009_report_outcome.sql
-- Report outcome notification: a filed report previously vanished into
-- silence when the LLM reviewed it and disagreed ("absence of rows = safe"
-- writes nothing) -- the reporter couldn't tell "reviewed and dismissed"
-- from "lost". Give each report a lifecycle the backend stamps after the
-- report-triggered re-scoring run (see backend report_service.py), and the
-- frontend streams over Realtime:
--
--   pending    -> filed, re-scoring not finished yet (default on insert)
--   confirmed  -> LLM agreed; score rows were written (source='user_report')
--   dismissed  -> LLM reviewed and disagreed; outcome_reasoning says why
--
-- Only the backend's service-role client writes these fields (bypasses
-- RLS; no UPDATE policy is added on purpose). The existing reporter-only
-- SELECT policy from migration 008 already covers the new columns.

alter table public.message_reports add column status text not null default 'pending'
  check (status in ('pending', 'confirmed', 'dismissed'));
alter table public.message_reports add column outcome_reasoning text;
alter table public.message_reports add column resolved_at timestamptz;

-- (No realtime change needed: migration 008 already added message_reports
-- to the supabase_realtime publication; UPDATE events flow automatically.)
