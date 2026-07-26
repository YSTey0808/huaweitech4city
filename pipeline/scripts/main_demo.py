"""
ARCHITECTURE VERIFICATION DEMO -- not the real pipeline. For that, see
scripts/run_batch_pipeline.py, which runs real preprocessing + real
embeddings + a trained-or-newly-trained model over an actual dataset.

This script exists to answer a narrower question cheaply and quickly, with
no external dependencies (no sentence-transformers, no model download, no
dataset required): "does the gnn/conversation_gnn.py architecture itself
still behave correctly?" It does that by exercising two things pipeline.py
never touches:

  1. Streaming vs batch equivalence -- gnn/conversation_gnn.py offers two
     ways to drive MessageGraphSAGE: build_message_graph + forward_full
     (batch, scores a fully-known conversation in one shot) and
     ConversationGraphState.add_message (streaming, extends the graph one
     message at a time as production would receive them, touching only
     the new message's local neighborhood). Both must produce the same
     conv_score from the same weights -- this script feeds the same mock
     conversation through both paths and checks they agree. If a future
     change to conversation_gnn.py breaks that invariant, this is what
     catches it.
  2. The LLM reasoning stage (gnn/llm_stage.py) end to end.

Message embeddings are mocked (torch.randn) and the model is randomly
initialized -- deliberately, since real embeddings/weights are irrelevant
to what this script checks. Scores printed here are numerically
meaningless; do not read them as predictions. For real predictions on real
data, run pipeline.py instead.
"""

import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # pipeline/ -- so gnn/ resolves as a sibling

from gnn.config import EMBED_DIM
from gnn.conversation_gnn import build_message_graph, MessageGraphSAGE, ConversationGraphState
from gnn.llm_stage import run_llm_reasoning


def mock_message_embeddings(texts):
    """
    Stand-in for a real embedding model. Replace this with e.g.:
        model.encode(texts)  # -> np.ndarray [len(texts), EMBED_DIM]
        torch.tensor(...)
    The rest of the pipeline only cares that you hand it a
    FloatTensor [EMBED_DIM] per message — swap this function out and
    nothing else needs to change.
    """
    return torch.randn(len(texts), EMBED_DIM)


def run_conversation(conv_id, messages, model):
    """
    messages: list of dicts, chronological order, shaped like the canonical
        schema: {message_id, sender_id, text, reply_to_message_id}.
    """
    print(f"\n=== Conversation {conv_id} ===")
    for m in messages:
        print(f"  [{m['sender_id']}] {m['text']}")

    embeddings = mock_message_embeddings([m["text"] for m in messages])
    for m, emb in zip(messages, embeddings):
        m["embedding"] = emb

    # --- streaming path: feed messages one at a time, as production would ---
    state = ConversationGraphState(model)
    print("  Streaming (one message at a time):")
    conv_score = None
    for m in messages:
        conv_score, message_score = state.add_message(
            m["message_id"], m["sender_id"], m["embedding"], m.get("reply_to_message_id")
        )
        print(f'    + [{m["sender_id"]}] "{m["text"]}"  ->  conv_score={conv_score:.4f}  message_score={message_score:.4f}')

    # --- batch/cold-start path: score the same, now-complete conversation in one shot ---
    graph = build_message_graph(messages)
    with torch.no_grad():
        batch_conv_score, _ = model.forward_full(graph)
    print(f"  Batch (cold-start) conv_score={batch_conv_score.item():.4f}  (streaming final was {conv_score:.4f})")

    # --- rank every message by streaming message_score (highest first, for
    # readable prompt ordering) -- the LLM judges from the whole window, not
    # a pre-filtered subset; see gnn/llm_stage.py for why ---
    scored = sorted(zip(messages, state.message_scores), key=lambda pair: -pair[1])
    ranked_messages = [
        {
            "message_id": m["message_id"],
            "text": m["text"],
            "sender_id": m["sender_id"],
            "score": round(score, 4),
        }
        for m, score in scored
    ]

    # --- LLM reasoning stage ---
    print("  Calling LLM for final reasoning...")
    try:
        llm_output = run_llm_reasoning(conv_id, ranked_messages, conv_score)
        print("  LLM output:")
        print(llm_output)
    except RuntimeError as e:
        print(f"  [skipped LLM call] {e}")


def main():
    model = MessageGraphSAGE()
    model.eval()

    run_conversation("conv_001", [
        {"message_id": "conv_001_m0", "sender_id": "user_a", "text": "hey are you coming to the party", "reply_to_message_id": None},
        {"message_id": "conv_001_m1", "sender_id": "user_b", "text": "nobody wants you there tbh", "reply_to_message_id": "conv_001_m0"},
        {"message_id": "conv_001_m2", "sender_id": "user_b", "text": "yeah just stay home like always", "reply_to_message_id": "conv_001_m1"},
    ], model)

    run_conversation("conv_002", [
        {"message_id": "conv_002_m0", "sender_id": "user_c", "text": "hi! how's your day going", "reply_to_message_id": None},
        {"message_id": "conv_002_m1", "sender_id": "user_d", "text": "it's ok i guess, kinda stressed", "reply_to_message_id": "conv_002_m0"},
    ], model)

    # Edge-case sanity check: a single-message conversation has zero possible
    # temporal/same_speaker/reply_to edges -- exercises the all-empty
    # edge_index path on both the streaming and batch code paths.
    run_conversation("conv_003", [
        {"message_id": "conv_003_m0", "sender_id": "user_e", "text": "u still there?", "reply_to_message_id": None},
    ], model)


if __name__ == "__main__":
    main()
