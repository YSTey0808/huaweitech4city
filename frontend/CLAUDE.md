# Project: Harm-Detection Chat Web App

## Goal

A responsive web app (phone + PC browser) for detecting harm in
code-mixed Singlish/Manglish/Mandarin chat. Judges access it via a
shared link. The ML model is built/hosted by a teammate — this repo
only CALLS it.

## CURRENT STAGE: real model integrated

This file originally documented the standalone prototype stage of
`tech4city_app`, when it was a separate repo and scoring was a keyword
mock. It has since been merged (via `git subtree`, history preserved)
into this monorepo as `frontend/`, alongside `backend/` (FastAPI) and
`pipeline/` (the actual GNN + LLM recognition engine) — see the root
`README.md` and `docs/` for the current architecture. The sections
below are kept for frontend-specific conventions (schema, UI rules,
responsive layout) but treat "Model contract" and "Mock scoring
behaviour" as historical — `docs/backend.md` and `docs/pipeline.md` are
the current source of truth for how scoring actually works now.

## Features (in build order)

1. Auth — Supabase email/password login + signup
2. Profile — display name, avatar colour (profiles table)
3. Friends — add friend by email/username; list friends (minimal:
   no request/accept flow unless I ask)
4. Chat — 1-to-1 realtime DM using Supabase Realtime, text only
5. Harm alerts (mock) — new messages get scored by a mock Edge
   Function; alerts appear on flagged messages + a conversation banner

## Tech stack (do not deviate)

- React + Vite + TypeScript + Tailwind CSS
- @supabase/supabase-js for ALL data, auth, and realtime
- No backend logic lives in `frontend/` itself. Scoring is triggered
  via the Supabase Edge Function (`score-message`), which is now a thin
  proxy forwarding to the real `backend/` service — see docs/backend.md.

## Database (Supabase / Postgres) — contract-aligned, do not simplify

- profiles(id uuid PK -> auth.users, username text unique,
  display_name text, avatar_color text)
- friendships(user_id, friend_id, created_at) — simple two-row insert
- conversations(id uuid PK, is_group bool default false, created_at)
  -- conversations.id serves as the model contract's conversation_id
- conversation_members(conversation_id, user_id)
- messages(id uuid PK, conversation_id, sender_id, content text,
  msg_type text default 'text',
  reply_to uuid null references messages(id),
  created_at timestamptz default now())
  -- prototype is text-only; msg_type and reply_to exist so the schema
  -- matches the model contract and never needs rebuilding.
  -- receiver_id is NOT stored (derived: the other DM member).
  -- Timestamps stored as timestamptz; converted to epoch ms only when
  -- building a model payload (later stage).
- message_scores(id uuid PK, msg_id uuid references messages(id),
  label text, confidence float, created_at timestamptz default now())
- conversation_scores(id uuid PK,
  conversation_id uuid references conversations(id),
  label text, confidence float, evidence_msg_ids uuid[],
  severity text, reasoning text,
  created_at timestamptz default now())
  -- absence of rows = safe; scoring only writes problems found
  -- severity/reasoning added in migration 007 once the real model (see
  -- ../pipeline/, ../backend/) replaced the mock -- the LLM reasoning stage
  -- returns both and the old "no extra fields" assumption below no longer
  -- holds for these two.
- RLS on everything: users only see conversations they're members of,
  only their own profile is editable, scores visible only to members
  of the relevant conversation.
- Realtime enabled on: messages, message_scores, conversation_scores.

## Model contract (HISTORICAL — describes the original prototype agreement)

The original agreement, from when scoring was a mock: the model
receives a conversation window and returns
{ "message_scores": [{ msg_id, label, confidence }],
  "conversation_scores": [{ conversation_id, label, confidence, evidence_msg_ids }] }.
This still holds as the base shape (labels are open-ended harm types;
absence of rows = safe), but the real model additionally writes
`severity` and `reasoning` onto `conversation_scores` (migration 007) —
see `docs/backend.md` for the current, authoritative contract and
`docs/pipeline.md` for how the pipeline actually produces these fields.

## Scoring behaviour (HISTORICAL — this described the old keyword mock)

The mock's keyword-matching logic (scam/grooming keyword lists, last-10
window) has been replaced by the real `pipeline/` (preprocess -> embed
-> graph -> GNN -> LLM reasoning), fetched and written by `backend/`.
The Edge Function no longer scores anything itself — it only forwards
`{ conversation_id }` to the backend after an auth + membership check.
See `docs/backend.md` for what actually runs now.

## Harm alert UI (driven ONLY by contract fields)

- Message with a message_scores row -> highlight + small label badge
- Any conversation_scores row for the open conversation -> warning
  banner (label + confidence + severity badge + reasoning text);
  its evidence_msg_ids messages get highlighted
- Conversation list: badge on any conversation that has score rows
- Do not invent UI fields beyond what the DB schema actually has --
  severity/reasoning are legitimate now (the real model returns them),
  but nothing beyond those plus label/confidence/evidence_msg_ids

## Responsive layout (important — judges use phones)

- Wide (md+): conversation list left, chat centre, alert panel right
- Phone: single column; convo list -> tap into chat; alert panel is a
  pull-up bottom sheet or toggle tab. Must look good at 380px width.

## Rules for you (Claude Code)

- Build ONLY the feature I ask for in each conversation. Nothing extra.
- Show a plan and wait for approval before writing files.
- Never commit .env files. Use the repo root's .env.example with placeholder keys.
- Write SQL as migration files in supabase/migrations/ so schema is
  in git.
