-- 010_report_claim.sql
-- False-positive feedback: reports gain a direction. claim is what the
-- reporter asserts the message is:
--
--   'harmful' -> "the model missed this" (the original report flow)
--   'safe'    -> "the model flagged this wrongly" (dispute a false positive)
--
-- Both directions share the whole existing lifecycle (status /
-- outcome_reasoning / resolved_at from migration 009) and the same LLM
-- re-review; they differ in what a confirmation does (write score rows vs
-- annul them -- see backend report_service.py). Default 'harmful' backfills
-- every existing report correctly.
--
-- Note: unique(msg_id, reporter_id) from 008 still allows only ONE report
-- per user per message across both directions -- a user who reported a
-- message can't later also dispute it. Acceptable at this scope: the two
-- claims are opposing opinions about the same message from the same person.

alter table public.message_reports add column claim text not null default 'harmful'
  check (claim in ('harmful', 'safe'));
