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

A human-feedback report (user_report, see build_prompt) rides on this same
mechanism for free: since every message is already in view, a report never
needs to force anything into visibility -- it only adds one conversation
member's stated belief about a specific message as extra context for the
LLM's own judgment.

Confirmed past reports (confirmed_examples, see build_prompt) are the
generalizing half of that feedback loop before any retrain happens: messages
from OTHER conversations that a user reported and this stage then agreed
were harmful. They ride along as few-shot reference patterns in every
prompt, so a pattern confirmed once can inform the judgment on unrelated
conversations immediately -- the GNN's weights only learn it at the next
retrain (see docs). The caller supplies them as plain dicts; this module
stays free of any storage/Supabase knowledge.
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


def build_prompt(conversation_id, messages, conversation_score, user_report=None,
                 confirmed_examples=None):
    """
    messages: every message in the scoring window (not a GNN-filtered
        subset), each a dict {message_id, text, sender_id, score}. score is
        that message's contribution to conversation_score (see
        MessageGraphSAGE) -- a ranking signal from a small classifier that
        can be wrong, not ground truth and not an independent probability.
    conversation_score: float in [0,1] -- P(harmful) for the conversation as
        a whole, from MessageGraphSAGE's pooled conversation-level head.
        Also a signal to weigh, not ground truth.
    user_report: optional dict {message_id, reason} -- a human-feedback
        report filed by a conversation member who believes message_id is
        harmful despite the model not flagging it. Since every message is
        already visible to the LLM (see module docstring), this needs no
        forced-inclusion mechanism -- it's just extra context, framed as a
        strong signal to weigh, not an automatic override. `reason` is free
        user text embedded in the prompt -- same category of exposure as any
        other message's text above, not a new one.
    confirmed_examples: optional list of dicts {text, reason, label} --
        past user-reported messages (from any conversation) whose reports
        this same stage subsequently confirmed as harmful. Included as
        reference patterns so a confirmed miss generalizes to similar
        messages everywhere immediately, without waiting for a retrain.
        Framed as reference only -- resemblance is something to weigh, not
        an automatic match. Both `text` and `reason` are user-authored free
        text, same exposure category as the message lines above.
    """
    message_lines = [
        f'  - id={m["message_id"]}, sender={m["sender_id"]}, model_score={m["score"]:.2f}: "{m["text"]}"'
        for m in messages
    ]

    examples_section = ""
    if confirmed_examples:
        example_lines = [
            f'  - label={e["label"]}, reporter said "{e["reason"]}": "{e["text"]}"'
            for e in confirmed_examples
        ]
        examples_section = f"""

Known harmful patterns, previously reported by users and confirmed on
review (from other conversations -- reference patterns, not part of this
conversation). If any message above resembles one of these, weigh that
resemblance in your judgment; do not flag on resemblance alone if the
actual context here doesn't support it:
{chr(10).join(example_lines)}"""

    report_section = ""
    if user_report is not None:
        report_section = f"""

A member of this conversation has REPORTED message id={user_report["message_id"]}
as harmful, giving this reason: "{user_report["reason"]}"

Weigh this report as a meaningful human signal alongside your own reading of
the messages above -- a person in the conversation saw something worth
flagging, so you may conclude "harmful" even if the classifier's scores are
low. Do not rubber-stamp it either: conclude "harmful" only if the reported
message and its context actually support it, and always include the reported
message in top_evidence_messages with your assessment reflected in its tags."""

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
{chr(10).join(message_lines)}{examples_section}{report_section}

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


def run_llm_reasoning(conversation_id, evidence_messages, conversation_score, user_report=None,
                      confirmed_examples=None):
    prompt = build_prompt(conversation_id, evidence_messages, conversation_score,
                          user_report=user_report, confirmed_examples=confirmed_examples)
    client = _get_client()

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text
    return _extract_json(raw_text)
