"""
Generates message embeddings for a conversations JSONL file (canonical
schema, see docs/data_schema.md).

Wires together the two pieces that weren't previously connected:
  - preprocess.preprocess_message() (preprocess/pipeline.py) runs on every
    message's raw content before embedding, normalizing identifiers/PII
    while preserving tone-carrying casing/punctuation/emoji.
  - a real sentence-embedding model (SEA-LION ModernBERT Embedding) turns
    that normalized text into a vector.

load_embedding_model() and embed_conversations() are the reusable pieces --
pipeline.py imports them directly to embed in-memory without going through
disk. This script's own CLI (below) is a thin wrapper around the same two
functions that additionally saves the result as a .npz with two row-aligned
arrays, "message_id" and "embedding" -- a format train.py's
load_embeddings() already reads, so no changes are needed there to consume
a file produced by this script.

Usage:
    python embed.py --input-jsonl dataset/train.jsonl --output dataset/train_embeddings.npz
"""

import argparse

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from preprocess import preprocess_message
from train import load_conversations
from gnn.config import EMBED_DIM

DEFAULT_MODEL = "aisingapore/SEA-LION-ModernBERT-Embedding-600M"


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_embedding_model(model_name: str = DEFAULT_MODEL) -> SentenceTransformer:
    device = pick_device()
    print(f"Loading {model_name} on device={device}...")
    model = SentenceTransformer(model_name, device=device)

    actual_dim = model.get_embedding_dimension()
    if actual_dim != EMBED_DIM:
        print(
            f"WARNING: model's embedding dim ({actual_dim}) != gnn.config.EMBED_DIM "
            f"({EMBED_DIM}). Update EMBED_DIM in gnn/config.py before training, "
            f"or MessageGraphSAGE's input_proj will reject these vectors."
        )
    else:
        print(f"Embedding dim {actual_dim} matches gnn.config.EMBED_DIM -- OK.")
    return model


def embed_conversations(conversations: list, model: SentenceTransformer, batch_size: int = 32) -> dict:
    """
    Runs preprocess_message() on every message's content, then encodes all
    of them in one batched call. Returns message_id -> FloatTensor[EMBED_DIM]
    -- the same shape train.py's load_embeddings() produces from a saved
    file, so this can be fed straight into prepare_example() in-memory,
    with no disk round-trip.
    """
    message_ids, texts = [], []
    for conv in conversations:
        for m in conv["messages"]:
            message_ids.append(m["message_id"])
            texts.append(preprocess_message(m["content"]))

    print(f"Encoding {len(texts)} messages from {len(conversations)} conversations "
          f"(batch_size={batch_size})...")
    vectors = model.encode(texts, batch_size=batch_size, show_progress_bar=True)

    return {mid: torch.tensor(vec, dtype=torch.float32) for mid, vec in zip(message_ids, vectors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    model = load_embedding_model(args.model_name)
    conversations = load_conversations(args.input_jsonl)
    embeddings = embed_conversations(conversations, model, batch_size=args.batch_size)

    message_ids = list(embeddings.keys())
    vectors = np.stack([embeddings[mid].numpy() for mid in message_ids])
    np.savez(args.output, message_id=np.array(message_ids), embedding=vectors)
    print(f"Wrote {len(message_ids)} embeddings, shape={vectors.shape}, to {args.output}")


if __name__ == "__main__":
    main()
