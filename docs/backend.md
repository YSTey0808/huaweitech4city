# Backend

`backend/` is a thin FastAPI service. Its only jobs: receive the scoring trigger from the Edge Function, fetch a conversation's messages from Supabase, hand them to `pipeline/` for the actual recognition, translate the result into DB rows, and write them back. It owns no model logic — see [pipeline.md](pipeline.md) for that, and [architecture.md](architecture.md) for how the pieces connect.

## API contract

### `POST /score`

Called by `supabase/functions/score-message` (the proxy), never directly by the frontend.

**Headers:** `X-Backend-Secret: <BACKEND_SHARED_SECRET>` — request is rejected with `401` if this doesn't match.

**Request body:**
```json
{ "conversation_id": "uuid" }
```

**Response body** (one of):
```json
{ "conversation_scores": "safe", "message_scores_inserted": 0 }
{ "conversation_scores": "no_messages", "message_scores_inserted": 0 }
{ "conversation_scores": "inserted" | "updated", "message_scores_inserted": <int> }
```

The backend never returns the model's raw verdict to the caller — it writes directly to `conversation_scores` / `message_scores` in Supabase (service role), and the frontend picks the result up via its existing Realtime subscription (`frontend/src/hooks/useScores.ts`), exactly like it did with the old mock. This response body is just a small operational summary, not the contract the UI depends on.

## Request handling, step by step

1. `backend/app/api/routes/score.py` verifies `X-Backend-Secret`.
2. `backend/app/services/scoring_service.py::fetch_message_window()` reads the last `score_window_size` (default 10) messages for the conversation, oldest-first (matches the original mock's window).
3. `backend/app/services/message_mapper.py::supabase_row_to_pipeline_message()` translates each row: `id`→`message_id`, `content`→`text`, `reply_to`→`reply_to_message_id`, `created_at` (timestamptz)→`timestamp` (epoch seconds), `sender_id` unchanged. This is the exact field-name/units drift flagged in the old `PROJECT_CONTEXT.md` — see [data_schema.md](data_schema.md#known-schema-issues).
4. `backend/app/services/embedding_store.py::LocalEmbeddingStore.get_or_compute()` attaches an `embedding` to each message — cache hit for messages already scored before, compute (and persist) only for new ones.
5. `pipeline/inference.py::score_conversation()` runs preprocess → embed → graph → GNN → LLM reasoning and returns the structured verdict (see [pipeline.md](pipeline.md)).
6. `scoring_service.py::write_scores()` translates the verdict into rows:
   - If `conversation_label == "safe"`: write nothing (absence of rows = safe, same convention as the original mock).
   - Otherwise: upsert one `conversation_scores` row (`label`, `confidence`, `evidence_msg_ids`, `severity`, `reasoning`), and insert one `message_scores` row per evidence message (skipping ones that already have a row for that label) — same label for every evidence message, since the model produces one conversation-level verdict with per-message contribution scores, not independent per-message classifications.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Service-role key — bypasses RLS, server-side only, never expose to the frontend |
| `ANTHROPIC_API_KEY` | yes | Read directly by `pipeline/gnn/llm_stage.py`; validated at backend startup so a missing key fails fast instead of deep inside the first LLM call |
| `BACKEND_SHARED_SECRET` | yes | Must match what `supabase/functions/score-message` sends as `X-Backend-Secret` |
| `ALLOWED_ORIGINS` | no (default `http://localhost:5173`) | Comma-separated list, not JSON — simpler to set correctly in Render's env var UI |
| `CHECKPOINT_PATH` | no | Overrides the default (`pipeline/checkpoints/message_graph_sage_old.pt`, resolved relative to the repo layout — see `message_graph_sage_new.pt` for the newer-dataset checkpoint, not yet promoted to default) |
| `EMBEDDING_DB_PATH` | no | Overrides the default local embedding cache location (`backend/data/embeddings.sqlite3`) |

Copy the `backend/.env` section of the repo root's `.env.example` into `backend/.env` for local dev.

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r ../pipeline/requirements.txt -r requirements.txt
cp ../.env.example .env   # keep only the `backend/.env` section, fill in real values
uvicorn app.main:app --reload
```

Or via Docker from the repo root:

```bash
docker compose up backend
```

To exercise the full pipeline locally: run `supabase start` (repo root), `npm run dev` (`frontend/`), and the backend (above) together, then send a message containing known-harmful phrasing and confirm the alert banner + reasoning appear via Realtime.

## Graph storage & lifecycle

See [architecture.md](architecture.md#graph-storage--lifecycle) for the full explanation. Short version: the message graph (`HeteroData`) is never persisted — rebuilt fresh from message metadata on every request. Only the model checkpoint and the message *embeddings* are cached, the latter via `LocalEmbeddingStore` (SQLite, `backend/data/embeddings.sqlite3`, gitignored).

## Deployment

The `frontend/` / `backend/` / `pipeline/` split was chosen partly to support hosting `frontend/` and `backend/` on separate platforms with zero restructuring:

- **Vercel → `frontend/`**: set the project's Root Directory to `frontend/`. Vercel builds/deploys only that subtree. Env vars: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.
- **Render → `backend/` (Docker)**: Root Directory must stay the **repo root** (not `backend/`), with a separate **Dockerfile Path = `backend/Dockerfile`** setting. This keeps the Docker build context large enough for `COPY pipeline/...` to reach the sibling `pipeline/` directory — setting Root Directory to `backend/` scopes the build context there and breaks the build (confirmed against [Render's monorepo docs](https://render.com/docs/monorepo-support): "files outside your service's root directory are not available... at build time"). Env vars: all of the table above.
  - Leaving Root Directory at repo-root means Render would otherwise redeploy the backend on *any* commit anywhere in the repo, including pure frontend changes. Use Render's **Build Filters** setting (paths relative to repo root regardless of Root Directory) scoped to `backend/**` + `pipeline/**` to restore "only redeploy when relevant files change."
- **Checkpoint delivery**: `pipeline/checkpoints/*.pt` is committed directly to git (a few MB) — Render's build just `COPY`s it in like any other file, no Git LFS or separate fetch step needed.
- **CORS**: `ALLOWED_ORIGINS` should list the Vercel prod domain + preview-deployment pattern once frontend and backend are on different origins.
- **Wiring the proxy**: once Render assigns a public URL, set it as `BACKEND_URL` (+ matching `BACKEND_SHARED_SECRET`) in the Supabase Edge Function's secrets (`supabase secrets set`), so `score-message/index.ts` forwards to the right place.
- **Scaling caveat**: `LocalEmbeddingStore` (SQLite-on-local-disk) is fine for a single Render instance, but doesn't survive horizontal scaling — each replica gets its own empty on-disk cache (Render doesn't share local disk across replicas, and persistent disks are single-instance-only). Multiple replicas is the natural trigger to build a `SupabaseEmbeddingStore` (same `EmbeddingStore` interface, Postgres/pgvector-backed) as a drop-in swap — not built yet, since it isn't needed until then.

## Privacy note

Persistently caching real message embeddings is a privacy-relevant decision — this repo already treats that seriously (`pipeline/scripts/anonymize_dataset.py`). Worth revisiting retention policy once a `SupabaseEmbeddingStore` moves this cache from a local, easy-to-wipe SQLite file to shared infrastructure.
