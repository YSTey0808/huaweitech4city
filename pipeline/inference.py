"""
Single-conversation scoring entrypoint -- the handoff point backend/ calls
after fetching a conversation's message window and attaching embeddings
(see backend/app/services/embedding_store.py). Reuses the exact same
stage functions gnn/conversation_gnn.py and gnn/llm_stage.py already
expose -- no new pipeline logic, matching scripts/run_batch_pipeline.py's
"one implementation per stage" principle.

Like embed.py/train.py, this module is meant to be imported with pipeline/
itself on sys.path (not as a `pipeline` package) -- see backend/app/main.py
for how it's loaded.

Expected message shape (chronological order), already embedded upstream:
    message_id             str
    sender_id              str
    text                   str   -- sent to the LLM stage alongside every
                                     other message in the window, never fed
                                     into the graph/GNN itself
    embedding               FloatTensor[EMBED_DIM]
    reply_to_message_id    str | None

Graph edges (temporal/same_speaker/reply_to) are rebuilt fresh from message
metadata on every call via build_message_graph() -- cheap over a small
window, and keeps this function stateless. See docs/backend.md's "Graph
storage & lifecycle" for why only embeddings are cached, never the graph.
"""

import json

import torch

from gnn.conversation_gnn import build_message_graph, MessageGraphSAGE
from gnn.llm_stage import run_llm_reasoning


def _parse_llm_json(raw_text: str) -> dict:
    """The prompt asks Claude to respond with ONLY a JSON object, but it
    sometimes wraps it in a ```json ... ``` markdown fence anyway -- strip
    one if present before parsing, rather than letting json.loads fail on
    the leading backticks (observed in practice, not a hypothetical)."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text.strip())


def rank_messages(messages: list, per_message_scores: torch.Tensor) -> list:
    """
    Ranks every message in the window by its contribution score (see
    MessageGraphSAGE's conv_head docstring for why this is a principled
    per-message signal) -- highest first, for readable prompt ordering.
    Unlike an earlier version of this function, nothing is filtered out:
    the LLM stage judges from every message in the window, not a
    GNN-selected top-k -- see gnn/llm_stage.py's module docstring for why
    (a single-message conversation could never be second-guessed under the
    old top-k filter, since the one message and the conversation score are
    mathematically identical in that case; a longer conversation's real
    evidence could also be excluded if it didn't happen to score highest).

    This also means a human-feedback report never needs to force a message
    into visibility (an earlier version of this function had a
    force_include_id param for exactly that) -- every message the reported
    one is already unconditionally in this output. The only remaining
    responsibility of the caller with a report is passing it to
    run_llm_reasoning so the LLM knows to weigh it.
    """
    scored = sorted(
        zip(messages, per_message_scores.tolist()),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [
        {"message_id": m["message_id"], "sender_id": m["sender_id"], "text": m["text"], "score": score}
        for m, score in scored
    ]


@torch.no_grad()
def score_conversation(conversation_id: str, messages: list, model: MessageGraphSAGE,
                        user_report: dict = None) -> dict:
    """
    messages: chronological, already embedded (see module docstring).
    model: a loaded MessageGraphSAGE in eval mode (caller loads this once
        at startup -- see backend/app/main.py -- and passes it in here so
        it's never reloaded per request).
    user_report: optional {message_id, reason} -- a human-feedback report
        (backend POST /report). The reported message is already guaranteed
        to be in `messages` (report_service.py anchors the fetched window on
        it) and already guaranteed visible to the LLM (rank_messages filters
        nothing) -- user_report only needs to reach run_llm_reasoning so the
        LLM knows to weigh it.

    Returns the LLM stage's structured verdict -- the LLM's own judgment,
    not a passthrough of the GNN's label (see gnn/llm_stage.py):
        {conversation_label, conversation_confidence, severity,
         top_evidence_messages: [{message_id, text, score, tags}],
         gentle_alert_text}

    No score-based short-circuit: an earlier version skipped the LLM call
    entirely when the GNN's conv_score was very low, on the reasoning that a
    "safe" verdict writes no rows anyway. Removed because it directly
    undermined this module's own design principle (see gnn/llm_stage.py) --
    the GNN is least reliable on exactly the short/sparse conversations most
    likely to produce a low score by chance, and a skipped call means
    nothing ever gets to override a bad guess there. Always calling the LLM
    is the correct tradeoff at current message volume.
    """
    model.eval()
    graph = build_message_graph(messages)
    conv_score, per_message_scores = model.forward_full(graph)

    ranked = rank_messages(messages, per_message_scores)
    raw_json = run_llm_reasoning(conversation_id, ranked, conv_score.item(), user_report=user_report)
    return _parse_llm_json(raw_json)
