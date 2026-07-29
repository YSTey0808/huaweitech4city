-- 011_report_escalation.sql
-- Human-review escalation: when the LLM DISMISSES a report (disagreed with
-- the reporter -- either "we don't think it's harmful" for a claim='harmful'
-- report, or "the flag stands" for a claim='safe' dispute), the reporter can
-- escalate for a second, human opinion. escalated_at is the durable signal a
-- reviewer/retraining pipeline queries:
--
--   select * from public.message_reports where escalated_at is not null;
--
-- These are the human-vs-model disagreements a person deemed worth a closer
-- look -- exactly the high-signal examples worth prioritising for review and
-- eventual retraining.
--
-- The escalation write is deliberately NOT a broad UPDATE policy: an UPDATE
-- policy can scope which ROWS a reporter may touch but not which COLUMNS, so
-- it would also let them edit reason / flip status / clear outcome_reasoning
-- on their own row. Instead a SECURITY DEFINER RPC (mirroring 001's
-- is_conversation_member and the open_dm / get_dm_overview helpers) pins the
-- write to exactly escalated_at, with every guard enforced server-side in one
-- authoritative place. message_reports otherwise stays an insert-only log.

alter table public.message_reports add column escalated_at timestamptz;

create or replace function public.escalate_report(
  _msg_id uuid,
  _conversation_id uuid
)
returns void
language sql
security definer
set search_path = public
as $$
  update public.message_reports
  set escalated_at = now()
  where msg_id = _msg_id
    and conversation_id = _conversation_id
    and reporter_id = auth.uid()   -- only your own report (auth.uid() reads the caller's JWT)
    and status = 'dismissed'       -- only a dismissed outcome is escalatable
    and escalated_at is null;      -- idempotent: re-clicking is a no-op, never resets the timestamp
$$;

grant execute on function public.escalate_report(uuid, uuid) to authenticated;
