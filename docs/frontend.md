# Frontend

`frontend/` is the chat UI — React + Vite + TypeScript + Tailwind CSS v4. It talks to Supabase directly for **all** auth, data, and Realtime; the only "backend call" it makes is triggering the scoring Edge Function after a send. It has no knowledge of `backend/` or `pipeline/` — see [architecture.md](architecture.md) for the full picture, and `frontend/CLAUDE.md` for the original detailed feature/schema spec this UI was built against.

This directory was merged in from a formerly-separate repo (`tech4city_app`) via `git subtree`, with commit history preserved.

## Structure

```
frontend/
├── src/
│   ├── main.tsx                boots React; shows a config-error screen if Supabase env vars are missing
│   ├── App.tsx                  route table (login/signup public-only; profile/friends/chat/reports protected)
│   ├── pages/                   ChatPage, FriendsPage, LoginPage, ProfilePage, ReportsPage, SignupPage
│   ├── components/
│   │   ├── ChatPane.tsx           message list, composer, harm-flag highlighting, alert banner
│   │   ├── AlertPanel.tsx          safety-alert detail — conversation + message-level scores, severity, reasoning
│   │   ├── ConversationList.tsx
│   │   ├── AppLayout.tsx, Avatar.tsx, Spinner.tsx
│   │   └── ProtectedRoute.tsx, PublicOnlyRoute.tsx
│   ├── hooks/
│   │   ├── useMessages.ts         message history + Realtime subscription + optimistic send;
│   │   │                          fires the scoring trigger after insert (see below)
│   │   ├── useConversations.ts    DM list via RPC `get_dm_overview` + Realtime
│   │   ├── useScores.ts           message_scores / conversation_scores Realtime subscription
│   │   ├── useFlaggedConversations.ts
│   │   └── useFriends.ts, useReports.ts
│   ├── context/AuthContext.tsx   Supabase auth/session/profile context
│   ├── lib/
│   │   ├── supabase.ts            createClient() + supabaseConfigured guard
│   │   └── conversations.ts       openOrCreateDm() via RPC open_dm
│   └── types/db.ts               TS row types mirroring the Supabase schema (see below)
├── index.html, vite.config.ts, tsconfig*.json, package.json
└── vercel.json                   SPA rewrite config (deep links survive a hard refresh)
```

## How scoring gets triggered

`useMessages.ts` does two things on send:
1. `supabase.from('messages').insert(...)` — the message itself, straight to Postgres.
2. `supabase.functions.invoke('score-message', { conversation_id })` — fire-and-forget; a scoring failure never blocks or fails the message send.

The Edge Function (`supabase/functions/score-message`) is a thin proxy to `backend/` — see [backend.md](backend.md). The frontend never learns the result synchronously; `useScores.ts`'s Realtime subscription on `message_scores`/`conversation_scores` picks it up whenever the backend finishes writing (typically a few seconds later, once preprocessing → embedding → GNN → LLM reasoning completes).

## Harm alert UI

- A message with a `message_scores` row → highlighted + small label badge.
- Any `conversation_scores` row for the open conversation → warning banner: label, confidence, a **severity** badge, and a short **reasoning** sentence (both added in migration `007_add_llm_reasoning_fields.sql` once the real model replaced the mock — see [data_schema.md](data_schema.md#output-contract)). Its `evidence_msg_ids` messages get highlighted too.
- Conversation list: badge on any conversation that has score rows.
- Absence of rows = safe — nothing is written for safe conversations, so "no alert" and "not yet scored" look the same by design (matches the pipeline's own convention, see [pipeline.md](pipeline.md)).

## Database schema

Defined in `supabase/migrations/`, mirrored in `frontend/src/types/db.ts`:

- `profiles`, `friendships`, `conversations`, `conversation_members` — auth/social graph.
- `messages(id, conversation_id, sender_id, content, msg_type, reply_to, created_at)` — text-only today; `msg_type`/`reply_to` exist so the schema already matches the pipeline's canonical shape.
- `message_scores(id, msg_id, label, confidence, created_at)`.
- `conversation_scores(id, conversation_id, label, confidence, evidence_msg_ids, severity, reasoning, created_at)`.
- RLS everywhere: users only see conversations they're members of; scores visible only to members of the relevant conversation.
- Realtime enabled on `messages`, `message_scores`, `conversation_scores`.

## Environment variables

| Variable | Description |
| --- | --- |
| `VITE_SUPABASE_URL` | Supabase project URL (Dashboard → Settings → API) |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon/public key (client-safe by design) |

Never commit `.env` — it's gitignored; the repo root's `.env.example` holds the placeholders (`frontend/.env` section). If either variable is missing, the app shows a config-error screen instead of loading.

## Run locally

```bash
cd frontend
npm install
cp ../.env.example .env   # keep only the `frontend/.env` section, fill in real values
npm run dev            # http://localhost:5173
```

- `npm run dev` — start the dev server
- `npm run build` — type-check (`tsc -b`) and build for production
- `npm run preview` — preview the production build

## Supabase setup

1. Create a Supabase project and link it: `supabase link --project-ref <your-project-ref>` (run from the repo root — `supabase/` is shared infra, not inside `frontend/`).
2. Apply the migrations in [`supabase/migrations/`](../supabase/migrations/) (`supabase db push`). They create all tables, RLS policies, and enable Realtime on `messages`, `message_scores`, and `conversation_scores`.
3. Deploy the proxy function: `supabase functions deploy score-message`, and set its secrets (`BACKEND_URL`, `BACKEND_SHARED_SECRET`) — see [backend.md](backend.md#deployment).

## Deploy to Vercel

1. Import the repo, set **Root Directory to `frontend/`** — Vercel auto-detects Vite (`npm run build`, output `dist/`). See [backend.md](backend.md#deployment) for why this matters once `backend/` is deployed separately (Render).
2. Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` under Project Settings → Environment Variables. Vite inlines env vars at build time, so **redeploy after changing them**.
3. `vercel.json` rewrites all routes to `index.html` so deep links like `/chat/:id` survive a hard refresh.
