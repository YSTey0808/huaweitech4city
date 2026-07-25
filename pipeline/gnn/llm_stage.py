"""
LLM reasoning stage.

Deliberately receives only a small, pre-scored evidence bundle — not the
raw conversation and not any model internals — to keep this call cheap and
fast. Evidence selection is top-k by each message's contribution score from
MessageGraphSAGE (see gnn/conversation_gnn.py): the same conv_head weights
used for the conversation-level verdict, applied per-message before
pooling, so it costs zero extra trained parameters.
"""

import os
import json

from dotenv import load_dotenv
from anthropic import Anthropic

from .config import CONV_LABELS, LLM_MODEL

load_dotenv()

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Copy the backend/ section of the repo root's "
                ".env.example into backend/.env and fill it in."
            )
        _client = Anthropic(api_key=api_key)
    return _client


def build_prompt(conversation_id, evidence_messages, conversation_score):
    """
    evidence_messages: list of dicts {message_id, text, sender_id, score}
        score = sigmoid of that message's contribution to conversation_score
        (see MessageGraphSAGE) — a ranking/evidence signal, not an
        independent per-message probability.
    conversation_score: float in [0,1] — P(harmful) for the conversation as
        a whole, from MessageGraphSAGE's pooled conversation-level head.
    """
    evidence_lines = [
        f'  - id={m["message_id"]}, sender={m["sender_id"]}, score={m["score"]:.2f}: "{m["text"]}"'
        for m in evidence_messages
    ]

    prompt = f"""You are a content-safety reasoning assistant. You are given a
pre-computed risk score from an upstream GraphSAGE classifier for a single
conversation, plus the top evidence messages it flagged. Do not re-derive
the score from scratch — use it as ground truth signal and produce a
concise, human-readable explanation a trust & safety reviewer (or the
affected teen) could quickly understand.

Conversation ID: {conversation_id}

Label vocabulary: {CONV_LABELS}

Conversation-level risk score (probability this conversation is harmful):
{conversation_score:.4f}

Top evidence messages (score = this message's share of responsibility for
the score above; higher = more responsible, not an independent probability):
{chr(10).join(evidence_lines)}

Respond with ONLY a JSON object in this exact shape:
{{
  "conversation_label": "<one of {CONV_LABELS}>",
  "conversation_confidence": <float 0-1>,
  "severity": "<low|medium|high>",
  "top_evidence_messages": [
    {{"message_id": "...", "text": "...", "score": <float>, "tags": ["..."]}}
  ],
  "gentle_alert_text": "<one short sentence suitable for showing directly to the user>"
}}"""
    return prompt


def _extract_json(text: str) -> str:
    """
    The model is asked for a bare JSON object, but LLMs often wrap it in
    ```json ... ``` fences or add a sentence before/after it. Pull out the
    outermost {...} object so json.loads() downstream gets clean input.
    Raises with the raw text if no object is present (empty reply, refusal),
    so the failure is diagnosable instead of an opaque JSONDecodeError.
    """
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"LLM did not return a JSON object. Raw response:\n{text!r}")
    return text[start : end + 1]


def run_llm_reasoning(conversation_id, evidence_messages, conversation_score):
    prompt = build_prompt(conversation_id, evidence_messages, conversation_score)
    client = _get_client()

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text
    return _extract_json(raw_text)
