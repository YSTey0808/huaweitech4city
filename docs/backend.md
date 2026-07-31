# Backend

`backend/` is a thin FastAPI service. Its only jobs: receive the scoring trigger from the Edge Function, fetch a conversation's messages from Supabase, hand them to `pipeline/` for the actual recognition, translate the result into DB rows, and write them back. It owns no model logic — see [pipeline.md](pipeline.md) for that, and [architecture.md](architecture.md) for how the pieces connect.

## API contract

Two audiences, and the split matters:

- **Internal** — `POST /score` and `POST /report`, below. Called only by our own Supabase Edge Function proxies. They take a `conversation_id`, re-fetch the messages from our Supabase, and write verdict rows the frontend reads over Realtime. Gated by the single shared `X-Backend-Secret`.
- **Public** — `POST /v1/analyze`, the partner API. Stateless in both directions: messages in the request, verdict in the response, no product table touched. Per-partner API keys, rate limited. Documented separately in **[public_api.md](public_api.md)** — that file is the published contract, so treat renames there as breaking changes.

Both go through the same `pipeline/inference.py::score_conversation()`; a partner is never served a different model than our own users.

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

### `POST /report`

The human-feedback entrypoint — a user telling the system it got a message wrong. Called by `supabase/functions/report-message` (a second thin proxy, same shape as `score-message`), never directly by the frontend. Same `X-Backend-Secret` gate as `/score`.

**Request body:**
```json
{ "conversation_id": "uuid", "msg_id": "uuid", "reason": "string", "claim": "harmful" | "safe" }
```

`claim` is the report's direction:
- `"harmful"` — "the model **missed** this" (a message the user believes is harmful but wasn't flagged).
- `"safe"` — "the model **flagged** this wrongly" (a false-positive dispute of an existing flag).

`reason` is the user's free-text explanation; rejected with `422` if blank (`backend/app/schemas/report.py`).

**Response body** (`conversation_scores` field, one of):
```json
{ "conversation_scores": "message_not_found", "message_scores_inserted": 0 }
{ "conversation_scores": "safe" | "inserted" | "updated", "message_scores_inserted": <int>, "report_status": "confirmed" | "dismissed" }
{ "conversation_scores": "annulled" | "flag_stands", "message_scores_inserted": 0, "report_status": "confirmed" | "dismissed" }
```

`report_status` is what the LLM decided **relative to the claim**: `confirmed` = the LLM agreed with the human, `dismissed` = it disagreed. For a `harmful` report `confirmed` means "yes, flag it"; for a `safe` dispute `confirmed` means "yes, this was a false positive" (`annulled`). Like `/score`, the UI doesn't depend on this body — it reads the resulting `conversation_scores` / `message_scores` (via `useScores.ts`) and `message_reports` outcome (via `useMessageReport.ts`) over Realtime.

## Request handling, step by step

1. `backend/app/api/routes/score.py` verifies `X-Backend-Secret`.
2. `backend/app/services/scoring_service.py::fetch_message_window()` reads the last 10 messages for the conversation — the `WINDOW_SIZE` constant in `scoring_service.py` — oldest-first (matches the original mock's window). (The `score_window_size` setting in `config.py` is not currently wired to this; the constant is the source of truth.)
3. `backend/app/services/message_mapper.py::supabase_row_to_pipeline_message()` translates each row: `id`→`message_id`, `content`→`text`, `reply_to`→`reply_to_message_id`, `created_at` (timestamptz)→`timestamp` (epoch seconds), `sender_id` unchanged. This is the exact field-name/units drift flagged in the old `PROJECT_CONTEXT.md` — see [data_schema.md](data_schema.md#known-schema-issues).
4. `backend/app/services/embedding_store.py::LocalEmbeddingStore.get_or_compute()` attaches an `embedding` to each message — cache hit for messages already scored before, compute (and persist) only for new ones.
5. `pipeline/inference.py::score_conversation()` runs preprocess → embed → graph → GNN → LLM reasoning and returns the structured verdict (see [pipeline.md](pipeline.md)).
6. `scoring_service.py::write_scores()` translates the verdict into rows:
   - If `conversation_label == "safe"`: write nothing (absence of rows = safe, same convention as the original mock).
   - Otherwise: upsert one `conversation_scores` row (`label`, `confidence`, `evidence_msg_ids`, `severity`, `reasoning`), and insert one `message_scores` row per evidence message (skipping ones that already have a row for that label) — same label for every evidence message, since the model produces one conversation-level verdict with per-message contribution scores, not independent per-message classifications.

## Report handling & the human-feedback loop

`POST /report` reuses the scoring machinery above with three differences (`backend/app/services/report_service.py`):

1. **The window is anchored on the reported message.** `fetch_message_window(..., up_to_message_id=msg_id)` ends the window *at* the reported message instead of "now", so a report on a message older than the last `WINDOW_SIZE` still gets scored in context (and doubles as the check that `msg_id` actually belongs to `conversation_id` — a mismatch returns `[]` → `message_not_found`).
2. **The report is passed to the LLM as context.** `score_conversation(..., user_report={message_id, reason, claim})` — the LLM is told a member reported/disputed this message and why, framed as a strong human signal to weigh, not an automatic override (see [pipeline.md](pipeline.md#llm-reasoning-stage)). It never re-runs the GNN's verdict blindly.
3. **The write depends on the claim + verdict:**
   - `harmful` report **confirmed** → `write_scores(..., source="user_report")`, same rows as `/score` but provenance-tagged.
   - `safe` dispute **confirmed** → `_annul_message_flags()` **deletes** the message's `message_scores` rows and prunes it from `conversation_scores.evidence_msg_ids` (deleting the conversation row if that was its only evidence). Absence-of-rows = safe means clearing a wrong flag is a delete, not a write.
   - Either **dismissed** → no score change; the existing state stands.

   Afterwards, `_record_report_outcome()` stamps the `message_reports` row(s) — scoped to `(conversation_id, msg_id, claim, status='pending')` so it can't overwrite an unrelated resolved report on the same message — with `status` / `outcome_reasoning` (the LLM's `gentle_alert_text`, which the prompt asks it to address to the reporter on a dismissal) / `resolved_at`. The reporter streams that outcome over Realtime.

### Watchlist — cross-conversation generalization

Every scoring call (automatic *and* report-triggered) fetches confirmed past reports as few-shot reference patterns for the LLM prompt — `backend/app/services/watchlist_service.py::SupabaseWatchlist.get_confirmed_examples()`. This is what lets a pattern confirmed once in one conversation inform the LLM's judgment on *every other* conversation immediately, before any retrain closes the gap in the GNN's weights.

- **"Confirmed" = `message_reports.status = 'confirmed'`** (the LLM agreed with the human), not merely "reported" — unreviewed/dismissed reports never reach other conversations' prompts, which is the poisoning guard against spam reports.
- Both directions feed it: confirmed `harmful` reports become "known harmful patterns", confirmed `safe` disputes become "known false-positive patterns" that nudge the LLM *away* from re-flagging similar ordinary messages.
- Fails safe (returns `[]` on any error — scoring never breaks) and is capped (`WATCHLIST_LIMIT`) to bound prompt growth. `WatchlistProvider` is a `Protocol` (mirroring `EmbeddingStore`), so a future similarity-based implementation (pgvector kNN over reported-message embeddings) can drop in behind the same method — the plain full-fetch is fine at current data volume.

### Escalation & retraining data

A dismissed report can be escalated for human review by the reporter (`escalate_report` RPC, migration 011) — a `SECURITY DEFINER` function pins the write to exactly `escalated_at`, so `message_reports` stays an insert-only log to any direct client write. Nothing in `backend/` acts on escalations yet; they're a durable, queryable signal (`select * from message_reports where escalated_at is not null`) of human-vs-model disagreements a person deemed worth review. More broadly, every confirmed report is already a joinable labeled example (`message_reports` + its message + `source='user_report'` score rows) for a future `train.py` retrain — the collection half of the loop is done; the scheduled retrain itself is the next operational step, deliberately manual (human review before merging) as the poisoning guard.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Service-role key — bypasses RLS, server-side only, never expose to the frontend |
| `ANTHROPIC_API_KEY` | yes | Read directly by `pipeline/gnn/llm_stage.py`; validated at backend startup so a missing key fails fast instead of deep inside the first LLM call |
| `BACKEND_SHARED_SECRET` | yes | Must match what `supabase/functions/score-message` sends as `X-Backend-Secret` |
| `ALLOWED_ORIGINS` | no (default `http://localhost:5173`) | Comma-separated list, not JSON — simpler to set correctly in Render's env var UI |
| `CHECKPOINT_PATH` | no | Overrides the default (`pipeline/checkpoints/message_graph_sage_new.pt`, the newer-dataset checkpoint now promoted to the served default; `message_graph_sage_old.pt` is the original-dataset checkpoint, kept for comparison/rollback) |
| `EMBEDDING_DB_PATH` | no | Overrides the default local embedding cache location (`backend/data/embeddings.sqlite3`) |

Copy the `backend/.env` section of the repo root's `.env.example` into `backend/.env` for local dev.

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r ../pipeline/requirements.txt -r requirements.txt
cp ../.env.example .env   # keep only the `backend/.env` section, fill in real values
uvicorn app.main:app --reload --env-file .env
```

> **`--env-file .env` matters locally.** `pipeline/gnn/llm_stage.py` reads
> `ANTHROPIC_API_KEY` via `os.getenv`, and its `load_dotenv()` resolves relative to
> the pipeline module — not `backend/.env` — so without `--env-file` the key isn't in
> the process environment and the first LLM call raises `ANTHROPIC_API_KEY not set`.
> (In production this is a non-issue: hosting platforms inject real environment
> variables.)

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
