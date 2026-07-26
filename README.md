# Harm Pattern Recognition Assistant

Real-time system that flags cyberbullying/grooming/scam patterns in code-mixed conversations. A user sends a message in the chat UI; it's preprocessed, embedded, assembled into a per-conversation graph, scored by a GraphSAGE GNN, explained by an LLM reasoning stage, and the resulting flag + reasoning show up back in the chat as an alert — usually within a few seconds.

This repo is a monorepo with three clearly separated pieces:

| Directory | What it is | Docs |
|---|---|---|
| [`frontend/`](frontend/) | The chat UI — React + Vite + TypeScript. Talks to Supabase directly for auth/messages/Realtime. | [docs/frontend.md](docs/frontend.md) |
| [`backend/`](backend/) | A thin FastAPI service — HTTP interface + Supabase I/O + contract translation. Owns no model logic. | [docs/backend.md](docs/backend.md) |
| [`pipeline/`](pipeline/) | The recognition engine — preprocess → embed → graph → GNN → LLM reasoning. No HTTP or Supabase knowledge. | [docs/pipeline.md](docs/pipeline.md) |
| [`supabase/`](supabase/) | Shared infra — DB schema (migrations) + the one proxy Edge Function both sides touch. | [docs/frontend.md](docs/frontend.md#supabase-setup) |

If you only remember one rule: **`frontend/` is the UI, `backend/` is the API server, `pipeline/` is the model.** Everything else follows from that.

## Architecture

![Component view: frontend, Supabase, backend, pipeline](docs/images/architecture-component-view.png)

The send is never blocked on scoring — a message appears instantly via Supabase Realtime, and the flag + reasoning arrive a few seconds later over that same channel once the pipeline finishes:

![Request flow: send message through to alert display](docs/images/architecture-request-flow.png)

Full breakdown (component responsibilities, why `pipeline/` is a sibling of `backend/` and not nested inside it, the exact file-to-file call chain, and how the message graph is and isn't persisted) is in **[docs/architecture.md](docs/architecture.md)**.

## Quick start

Three pieces, run together for the full golden path:

```bash
# 1. Supabase (schema + the proxy Edge Function) — from the repo root
supabase start
supabase db push
supabase functions deploy score-message

# 2. Backend (FastAPI + the pipeline)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r ../pipeline/requirements.txt -r requirements.txt
cp ../.env.example .env   # keep only the `backend/.env` section, fill in real values
uvicorn app.main:app --reload

# 3. Frontend
cd frontend
npm install
cp ../.env.example .env   # keep only the `frontend/.env` section, fill in real values
npm run dev             # http://localhost:5173
```

Or run the backend via Docker instead of a local venv: `docker compose up backend` from the repo root.

Send a message containing known-harmful phrasing (see `pipeline/dataset/` once populated — gitignored, ask the team) and confirm the alert banner + reasoning text appear via Realtime.

## Docs

- **[docs/architecture.md](docs/architecture.md)** — system diagrams, component responsibilities, call chain, graph storage & lifecycle.
- **[docs/frontend.md](docs/frontend.md)** — UI structure, Realtime contract, env vars, Supabase setup, Vercel deploy.
- **[docs/backend.md](docs/backend.md)** — `POST /score` API contract, env vars, local run, Docker, Render deployment.
- **[docs/pipeline.md](docs/pipeline.md)** — GNN + LLM architecture, design rationale, known limitations.
- **[docs/preprocessing.md](docs/preprocessing.md)** — message-text normalization spec.
- **[docs/data_schema.md](docs/data_schema.md)** — canonical dataset schema, task definition, known schema issues (live vs. training field-name drift).

## Dataset & checkpoints

`pipeline/dataset/` is gitignored — each team member populates it locally (get `train.jsonl`/`validation.jsonl` from the team channel; see [docs/pipeline.md](docs/pipeline.md) and [docs/data_schema.md](docs/data_schema.md) for the schema). `pipeline/checkpoints/` **is** committed to git (a few MB) so the backend's Docker build has a working model with no separate fetch step — see [docs/backend.md](docs/backend.md#deployment).
