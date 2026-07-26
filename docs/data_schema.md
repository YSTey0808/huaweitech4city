# Data schema & project context

Task definition, dataset schema, and known issues for `pipeline/` — adapted from the original `huaweitech4city/PROJECT_CONTEXT.md`. See [pipeline.md](pipeline.md) for the model architecture this data trains, and [backend.md](backend.md) for how live Supabase data gets mapped onto the schema below.

## Task

Real-time system that detects **scam, cyberbullying, and grooming** in code-mixed Singlish messaging. Goal: **empower user decisions** — surface flagged messages/patterns. It does **not** auto-block or auto-report.

The model never scores a message in isolation. It receives a **conversation** (ordered batch of messages) and produces a conversation-level score; per-message evidence scores fall out as a derived byproduct of that same score (not an independently trained signal — see [pipeline.md](pipeline.md#evidence-score-derivation)).

## Requirements (status as implemented)

- **Conversation-level head:** binary `harmful` / `safe`. **Confirmed, implemented** — the sole trained output (`MessageGraphSAGE.conv_head`), a single sigmoid mapping directly onto `binary_conversation_label`.
- **Message-level head:** **dropped** as a separately-trained head. Per-message scores still exist, but only as a byproduct of the conversation-level head's own weights applied per-node before pooling.
- **4-class typed head:** **dropped**, not implemented. `conversation_label`'s 4-class value is not currently a training target.
- **Eval metric:** macro-F1 (not accuracy) — implemented in `train.py`. Splits are currently **train/validation only**, no held-out test set yet.
- **GNN justification** (ship the GNN only if it beats a transformer-only baseline by more than seed variance): not yet formally validated — GraphSAGE was adopted directly.

## Languages

English, Malay, Mandarin, Tamil — and **code-mixed Singlish** across them.

**⚠️ Open conflict, not yet resolved:** the current `preprocess/` implementation ([preprocessing.md](preprocessing.md)) explicitly assumes **English/Singlish only, no Mandarin or Tamil scripts** — it treats non-Latin characters as obfuscation/spoofing signal. That's a real behavioral consequence: genuine Mandarin or Tamil text would currently be miscategorized by the spoofed-link/homoglyph logic. Someone needs to decide whether multilingual coverage was intentionally deferred for the first pass, or whether `preprocess/` needs to be extended.

## Architecture (status as implemented)

```
sentence-embedding model  ->  message-node graph  ->  GraphSAGE  ->  conversation-level binary score  ->  LLM reasoning stage
```

Full detail: [pipeline.md](pipeline.md).

- **Encoder:** confirmed — `aisingapore/SEA-LION-ModernBERT-Embedding-600M` (`embed.py`'s `DEFAULT_MODEL`), 1024-dim (`gnn/config.py`'s `EMBED_DIM`).
- **GNN:** confirmed — GraphSAGE (not R-GCN/GATv2), 2 layers, via PyTorch Geometric's `HeteroConv`+`SAGEConv`. Directed edges, 3 types: `temporal`, `same_speaker`, `reply_to`. **No fixed conversation window** (`same_speaker` edges are capped per-sender via `SAME_SPEAKER_WINDOW`, not the whole conversation).
- **LLM reasoning stage:** implemented, `gnn/llm_stage.py`.

## Tech stack

- PyTorch Geometric.
- Encoder — see above.
- Data stored as **JSONL** (one conversation per line).
- Compute: developed against MPS (Apple Silicon) and CPU; GPU/Colab remain viable, nothing compute-specific is hardcoded.

## Data schema (canonical training format)

JSONL, one conversation per line. Example:

```jsonl
{"conversation_id": "conv1_1", "binary_conversation_label": "harmful", "conversation_label": "scam", "user1_id": "user1_1", "user2_id": "user1_2", "messages": [{"message_id": "conv1_1_1", "sender_id": "user1_1", "recipient_id": "user1_2", "timestamp": "...", "content": "...", "reply_to_message_id": null, "message_label": "harmful", "message_label_reason": "redirection"}]}
```

**Conversation fields:** `conversation_id`, `binary_conversation_label`, `conversation_label`, `user1_id`, `user2_id`, `messages[]`
**Message fields:** `message_id`, `sender_id`, `recipient_id`, `timestamp`, `content`, `reply_to_message_id`, `message_label`, `message_label_reason`

### Target attributes

| Field | Level | Type | Use |
|---|---|---|---|
| `message_label` | message | binary (`harmful`/`safe`) | not currently trained on (see above) |
| `binary_conversation_label` | conversation | binary (`harmful`/`safe`) | **binary head** — trained directly. Precomputed from `conversation_label` (`safe -> safe`, else `harmful`) |
| `conversation_label` | conversation | typed (`scam`/`cyberbullying`/`grooming`/`safe`) | not currently a training target (4-class head dropped) |

### Conventions

- `conversation_id` = `conv<labeller_id>_<n>`, labeller_id 1–5 — **bookkeeping only**, the model must not parse meaning from it.
- `message_id` follows `<conversation_id>_<n>`.
- Safe messages: `message_label` = `"safe"`, `message_label_reason` = `null`.
- Dataset contains **multiple harm types** generated across labellers — not scam-only.

## Output contract

`pipeline/gnn/llm_stage.py`'s `run_llm_reasoning()` produces one JSON object per conversation:

```json
{
  "conversation_label": "harmful" | "safe",
  "conversation_confidence": 0.0,
  "severity": "low" | "medium" | "high",
  "top_evidence_messages": [
    { "message_id": "...", "text": "...", "score": 0.0, "tags": ["..."] }
  ],
  "gentle_alert_text": "one short sentence suitable for showing directly to the user"
}
```

`score` on each evidence message is that message's derived contribution to the conversation-level score, not an independently-calibrated per-message probability.

`backend/app/services/scoring_service.py` translates this into the Supabase contract the frontend actually reads — `conversation_scores` (`label`, `confidence`, `evidence_msg_ids`, `severity`, `reasoning`) and `message_scores` (`label`, `confidence` per evidence message). This translation layer is what the original `PROJECT_CONTEXT.md` flagged as "not implemented yet" — it now lives in `backend/`, not `pipeline/`, keeping the pipeline's own output format stable regardless of what any particular consumer's DB schema looks like. See [backend.md](backend.md).

## Scope

- **First pass:** 2-speaker DMs, text-only.
- **Deferred / future:** N-party group chats (`group_id`, array recipients, `msg_type`).

## Known schema issues

Live (Supabase) input and the canonical training schema above don't match field-for-field — `backend/app/services/message_mapper.py` is the translation layer that resolves this for every live request:

| Live (Supabase `messages` table) | Canonical (training JSONL) | Resolution |
|---|---|---|
| `id` | `message_id` | mapped 1:1 |
| `content` | `text`/`content` | mapped 1:1 (frontend is text-only today, so no URL-vs-text overloading in practice) |
| `reply_to` | `reply_to_message_id` | mapped 1:1 |
| `created_at` (timestamptz) | `timestamp` (Unix seconds in training data) | converted via `datetime.fromisoformat(...).timestamp()` |
| `sender_id` | `sender_id` | unchanged |

`msg_type` exists in the live schema (for future non-text support) but has no path through the current text-only model — flagged here in case group chat / non-text support is picked up later.
