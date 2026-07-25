"""
LLM reasoning stage.

The LLM is the final judge, not a narrator of the GNN's number. It receives
every message in the scoring window (not a GNN-selected subset) plus each
message's contribution score from MessageGraphSAGE (see
gnn/conversation_gnn.py) and the conversation-level score -- both framed as
signals to weigh, not ground truth. This matters because the GNN can be
confidently wrong in ways a language model can catch by actually reading the
text: a single-message conversation has no context to score from at all (see
MessageGraphSAGE.forward_full -- with one message, conv_score and that
message's own contribution score are mathematically the same number, so a
bad guess there is unfixable downstream unless something can override it),
and a longer conversation's real evidence could have been excluded if it
didn't happen to score highest. Sending the full window (already capped
small -- see backend/'s WINDOW_SIZE) instead of a pre-filtered top-k keeps
this affordable while giving the LLM enough to actually disagree with the
classifier when the text doesn't support it.
"""

import os

from dotenv import load_dotenv
from anthropic import Anthropic

from .config import CONV_LABELS, LLM_MODEL, TOP_K_EVIDENCE

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


def build_prompt(conversation_id, messages, conversation_score):
    """
    messages: every message in the scoring window (not a GNN-filtered
        subset), each a dict {message_id, text, sender_id, score}. score is
        that message's contribution to conversation_score (see
        MessageGraphSAGE) -- a ranking signal from a small classifier that
        can be wrong, not ground truth and not an independent probability.
    conversation_score: float in [0,1] -- P(harmful) for the conversation as
        a whole, from MessageGraphSAGE's pooled conversation-level head.
        Also a signal to weigh, not ground truth.
    """
    message_lines = [
        f'  - id={m["message_id"]}, sender={m["sender_id"]}, model_score={m["score"]:.2f}: "{m["text"]}"'
        for m in messages
    ]

    prompt = f"""You are a content-safety reasoning assistant. You are given every
message in a conversation's scoring window, plus a pre-computed risk score
from an upstream GraphSAGE classifier for the conversation as a whole and
for each individual message's contribution to that score.

Both scores are signals, not ground truth. The classifier is a small model
that can be confidently wrong -- most notably on very short conversations
(a single message has no context to score from at all, so its output there
can be close to arbitrary) or on patterns it saw little of during training.
Read the actual message text yourself and form your own independent
judgment. If the text doesn't actually support the classifier's score --
for example, an ordinary greeting scored as highly harmful in isolation --
say so plainly in gentle_alert_text and use your own label and confidence
instead of deferring to the classifier.

Conversation ID: {conversation_id}

Label vocabulary: {CONV_LABELS}

Upstream classifier's conversation-level estimate (probability this
conversation is harmful, per its own scoring):
{conversation_score:.4f}

All messages in this conversation's scoring window, with the classifier's
per-message contribution score (higher = the classifier attributes more
responsibility to that message for the score above -- not an independent
probability that this message alone is harmful):
{chr(10).join(message_lines)}

Respond with ONLY a JSON object in this exact shape:
{{
  "conversation_label": "<one of {CONV_LABELS}>",
  "conversation_confidence": <float 0-1>,
  "severity": "<low|medium|high>",
  "top_evidence_messages": [
    {{"message_id": "...", "text": "...", "score": <float>, "tags": ["..."]}}
  ],
  "gentle_alert_text": "<one short sentence suitable for showing directly to the user>"
}}
Cite at most {TOP_K_EVIDENCE} messages in top_evidence_messages -- whichever
ones actually justify your verdict in your own judgment, not necessarily the
classifier's highest-scoring ones."""
    return prompt


def run_llm_reasoning(conversation_id, messages, conversation_score):
    prompt = build_prompt(conversation_id, messages, conversation_score)
    client = _get_client()

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text
    return raw_text
