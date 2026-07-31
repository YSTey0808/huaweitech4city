# Public API — harm detection as a service

Keep your own chat stack. Add harm detection with one HTTP call.

`POST /v1/analyze` takes a conversation, returns a verdict. No account to create, no messages to migrate into our database, no model to host or fine-tune. If you already have a `sendMessage` handler, integration is a few lines inside it.

The model is built for **code-mixed Singlish / Manglish / Mandarin** chat — the register that off-the-shelf English moderation APIs read as gibberish and pass through clean. It judges a conversation as a graph (who replied to whom, who spoke when), not as isolated strings, so it catches escalation patterns that per-message keyword filters and single-message classifiers miss.

---

## Quick start

```bash
curl -X POST https://34.177.100.153.nip.io/v1/analyze \
  -H "X-API-Key: pk_live_..." \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "acme-thread-8891",
    "messages": [
      {"message_id": "m1", "sender_id": "u1", "text": "u home alone?"},
      {"message_id": "m2", "sender_id": "u2", "text": "ya why"},
      {"message_id": "m3", "sender_id": "u1", "text": "dont tell ur parents we talking ok"}
    ]
  }'
```

```json
{
  "conversation_id": "acme-thread-8891",
  "conversation_label": "harmful",
  "conversation_confidence": 0.87,
  "severity": "high",
  "top_evidence_messages": [
    {
      "message_id": "m3",
      "text": "dont tell ur parents we talking ok",
      "score": 0.91,
      "tags": ["grooming"]
    }
  ],
  "gentle_alert_text": "Someone is asking you to keep this conversation secret from your parents. That's a common tactic — you can talk to an adult you trust about it.",
  "model_version": "aisingapore/SEA-LION-ModernBERT-Embedding-600M"
}
```

Interactive reference with live request/response schemas: **<https://34.177.100.153.nip.io/docs>**.

---

## Request

| Field | Type | Required | Notes |
|---|---|---|---|
| `conversation_id` | string | no | Your thread identifier. A correlation handle only — echoed back untouched, never stored. |
| `messages` | array | **yes** | Chronological, oldest first. 1–50 items. |

Each item in `messages`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `message_id` | string | **yes** | Your identifier. Returned unchanged in `top_evidence_messages`. Must be unique within the request. |
| `sender_id` | string | **yes** | Your identifier for the author. Any stable opaque string — a hash is fine, we never resolve it to a person. |
| `text` | string | **yes** | The message as sent. Don't pre-translate or pre-clean; normalization is part of the model. |
| `timestamp` | number | no | Unix epoch seconds. Omit and array order is used instead. |
| `reply_to_message_id` | string | no | The `message_id` this replies to, if your product has threading. Improves accuracy — send it if you have it. |

**Which messages to send.** Send the recent window around the activity you care about, not the whole thread. Our own product scores the last 10 messages on each send. More context is better up to a point; the 50-message cap exists because each request is one LLM call and cost scales with window size.

## Response

| Field | Type | Notes |
|---|---|---|
| `conversation_id` | string \| null | Echoed from your request. |
| `conversation_label` | string | `"safe"` or `"harmful"`. |
| `conversation_confidence` | number | 0–1 confidence in the label. |
| `severity` | string \| null | `"low"` \| `"medium"` \| `"high"` when harmful; `null` when safe. |
| `top_evidence_messages` | array | The specific messages behind the verdict. Empty when safe. |
| `gentle_alert_text` | string \| null | A non-alarming, user-facing explanation you can surface directly in your UI. `null` when safe. |
| `model_version` | string | The embedding model backing this verdict. Changes here can shift scores; log it alongside verdicts you store. |

`score` inside `top_evidence_messages` is that message's **contribution to the conversation verdict** — a ranking signal for "which message drove this", not a standalone per-message probability. Don't threshold on it independently.

`gentle_alert_text` is written to be shown to the person in the conversation, not to a moderator. The product stance behind this API is to **inform the user, not to auto-block** — the alert explains the pattern and leaves the decision with them.

## Errors

| Status | Meaning |
|---|---|
| `401` | Missing, unknown, or revoked `X-API-Key`. |
| `422` | Malformed body — empty or oversized `messages`, duplicate `message_id`s, missing required fields. The response names the offending field. |
| `429` | Rate limit exceeded. Retry after the number of seconds in the `Retry-After` header. |
| `502` / `503` | Upstream model unavailable. Retry with backoff. |

Analysis is not part of your send path — treat it as advisory. If a call fails, deliver the message anyway and retry the analysis, rather than blocking your user on our availability.

## Authentication

Pass your key in the `X-API-Key` header on every request.

**Server-to-server only.** Your API key belongs on your backend. Never ship it to a browser or mobile client — anyone who opens devtools can read it and spend your quota. CORS is deliberately not opened for this endpoint, so a direct browser call fails by design rather than quietly encouraging you to expose the key.

Lost a key? It cannot be recovered — we store only a hash. Ask for a new one and we'll revoke the old.

## Rate limits

Default **20 requests/minute** per key. Every call runs a real GNN forward pass and an LLM reasoning call, so there is no such thing as a cheap request — batch your window rather than calling per keystroke. Contact us for a higher limit.

## Data handling

**We do not retain your users' messages.** Message text is embedded and scored in memory, and discarded when the response is sent. It is never written to any table.

What we log per call, and nothing more: which key called, when, how many messages, the resulting label, and how long it took. No message text. No sender identifiers. That's enforced by the `api_usage` schema itself, which has no column to put them in ([`supabase/migrations/013_partner_api.sql`](../supabase/migrations/013_partner_api.sql)).

Your verdicts do benefit from our feedback loop in one direction: patterns that our own users reported and that were subsequently confirmed harmful are supplied to the model as reference examples on every call, including yours. So detection improves across the network without your data ever entering it.

---

## For maintainers

**Minting and revoking keys** — from `backend/`, **on a trusted local machine**:

```bash
python scripts/mint_api_key.py --partner "Acme Chat"          # prints the key ONCE
python scripts/mint_api_key.py --partner "Demo" --rate-limit 60
python scripts/mint_api_key.py --list
python scripts/mint_api_key.py --revoke <key-id>
```

> ⚠️ `backend/scripts/mint_api_key.py` is **gitignored and therefore absent from a fresh clone and from the production VM** — deliberately, so a credential-minting tool never sits on an internet-facing host. If you need it, get the file from someone who has it. Full reasoning in [deploy_public_api.md](deploy_public_api.md#issuing-api-keys--judges-partners-teammates).

Revocation takes effect within 60s — `api_key_service` caches verified keys for that long to keep a Supabase round-trip off every request. `sudo systemctl restart backend` on the VM clears it immediately.

**Rate limits are per key**, stored in `api_keys.rate_limit_per_min` and enforced in-process by `rate_limiter.py`. There is no edit command — to change a limit, revoke and re-mint.

**How this differs from the internal path.** `POST /score` ([docs/backend.md](backend.md)) takes a `conversation_id` and re-fetches messages from our own Supabase, then writes `conversation_scores` / `message_scores` rows the frontend reads over Realtime. `POST /v1/analyze` shares the same model but is stateless in both directions: messages in the request, verdict in the response, no product table touched. `backend/app/services/public_scoring_service.py` is the stateless sibling of `scoring_service.py`, and both call the same `pipeline/inference.py::score_conversation()` — a partner is never served a different model than our own users.

**One trap worth knowing.** The public path deliberately does *not* use `LocalEmbeddingStore`. That cache is keyed by `(message_id, model_version)`, and partner `message_id`s are arbitrary client strings (`"m1"`, `"1"`) that collide across partners and with our own UUIDs — a hit would serve one partner another's cached vector. Partner requests embed fresh every call. See the comment in `public_scoring_service.py::analyze_messages`.
