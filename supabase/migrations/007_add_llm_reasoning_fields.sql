-- 007_add_llm_reasoning_fields.sql
-- The real scoring backend (pipeline/gnn/llm_stage.py's run_llm_reasoning)
-- returns a severity tier and a short human-readable explanation alongside
-- the label/confidence/evidence the mock scorer already produced. Neither
-- field existed in the original contract (CLAUDE.md's "Model contract"),
-- which only covers label/confidence/evidence_msg_ids -- add them so the
-- backend has somewhere to write the LLM's reasoning for the frontend to
-- display.

alter table conversation_scores add column severity text;
alter table conversation_scores add column reasoning text;
