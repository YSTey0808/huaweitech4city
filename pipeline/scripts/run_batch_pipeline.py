"""
Full pipeline orchestrator: given a conversations JSONL file, runs every
stage -- preprocessing -> embedding -> message-graph construction -> GNN
forward pass -- for every conversation in it, using a trained
MessageGraphSAGE.

Model handling: if --checkpoint already exists on disk, it's loaded
directly (training is skipped entirely). If it doesn't exist yet, a new
model is trained first -- always on the canonical training split
(dataset/train.jsonl + dataset/validation.jsonl), regardless of what
--input-jsonl points at -- and the resulting checkpoint is saved to
--checkpoint before inference proceeds. --input-jsonl is the file to run
the trained model over; it does not have to be the training data.

This is the real thing -- real preprocessing, real embeddings, a real
(trained-or-newly-trained) model, over an actual dataset. For a fast,
dependency-free check that the underlying architecture itself is still
wired correctly (streaming vs batch equivalence, the LLM stage), see
main_demo.py instead; it uses mock data on purpose and isn't meant to
produce real predictions.

This script doesn't introduce any new pipeline logic of its own -- it's an
orchestrator over the same functions train.py/embed.py already expose
(embed.embed_conversations, train.train_model, gnn.conversation_gnn's
build_message_graph + MessageGraphSAGE.forward_full), so there is exactly
one implementation of each stage in the repo.

Usage (run with pipeline/ as the working directory):
    cd pipeline && python scripts/run_batch_pipeline.py --input-jsonl dataset/train.jsonl
"""

import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # pipeline/ -- so embed/train/gnn resolve as siblings

from embed import DEFAULT_MODEL, load_embedding_model, embed_conversations
from train import (
    load_conversations, prepare_example, train_model, per_class_stats, macro_f1, print_validation_report,
)
from gnn.conversation_gnn import build_message_graph, MessageGraphSAGE


def bootstrap_checkpoint(checkpoint_path, embed_model, epochs: int, lr: float, pos_weight: float,
                          weight_decay: float, patience: int) -> MessageGraphSAGE:
    """No checkpoint exists yet -- train one from scratch on the canonical
    training split before this script can do anything else. Takes an
    already-loaded embed_model so the (slow-ish) model load only happens
    once per run, shared with the later inference stage."""
    print(f"No checkpoint found at {checkpoint_path} -- training a new model on "
          f"dataset/train.jsonl / dataset/validation.jsonl first.\n")

    train_convs = load_conversations("dataset/train.jsonl")
    val_convs = load_conversations("dataset/validation.jsonl")
    train_embeddings = embed_conversations(train_convs, embed_model)
    val_embeddings = embed_conversations(val_convs, embed_model)

    train_examples = [prepare_example(c, train_embeddings) for c in train_convs]
    val_examples = [prepare_example(c, val_embeddings) for c in val_convs]
    print(f"  train={len(train_examples)} conversations, val={len(val_examples)} conversations\n")

    model = train_model(train_examples, val_examples, epochs, lr, pos_weight, checkpoint_path,
                         weight_decay=weight_decay, patience=patience)
    print_validation_report(model, val_examples)
    return model


def run_inference(model: MessageGraphSAGE, input_jsonl: str, embed_model) -> None:
    """The four pipeline stages this script exists to demonstrate, run for
    every conversation in input_jsonl: preprocess -> embed -> build the
    message graph -> GNN forward pass."""
    print(f"\n--- Running pipeline on {input_jsonl} ---")

    print("[1/4] Loading conversations...")
    conversations = load_conversations(input_jsonl)
    print(f"      {len(conversations)} conversations")

    print("[2/4] Preprocessing + embedding every message...")
    embeddings = embed_conversations(conversations, embed_model)

    print("[3/4] Building message graphs + running GNN forward pass...")
    has_labels = all("binary_conversation_label" in c for c in conversations)
    y_true, y_pred = [], []
    model.eval()
    for i, conv in enumerate(conversations):
        messages, label = prepare_example(conv, embeddings)
        graph = build_message_graph(messages)
        with torch.no_grad():
            conv_score, _ = model.forward_full(graph)
        predicted = "harmful" if conv_score.item() >= 0.5 else "safe"

        if i < 10 or (i + 1) % 200 == 0:
            actual = f"  actual={conv['binary_conversation_label']}" if has_labels else ""
            print(f"      {conv['conversation_id']}: score={conv_score.item():.4f}  predicted={predicted}{actual}")

        if has_labels:
            y_true.append(int(label))
            y_pred.append(int(conv_score.item() >= 0.5))

    print("[4/4] Done.")

    if has_labels:
        stats = per_class_stats(y_true, y_pred)
        label_name = {0: "safe", 1: "harmful"}
        print(f"\nResults on {input_jsonl} ({len(conversations)} conversations):")
        for cls in (0, 1):
            s = stats[cls]
            print(f"  {label_name[cls]:8s}  precision={s['precision']:.4f}  recall={s['recall']:.4f}  "
                  f"f1={s['f1']:.4f}  (tp={s['tp']} fp={s['fp']} fn={s['fn']})")
        print(f"  macro_f1={macro_f1(y_true, y_pred):.4f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-jsonl", default="dataset/train.jsonl")
    parser.add_argument("--checkpoint", default="checkpoints/message_graph_sage_old.pt")
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--pos-weight", type=float, default=1.0)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=None,
                         help="stop early after this many epochs with no new best val_macro_f1")
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint)
    embed_model = load_embedding_model(args.model_name)  # needed either way: to train, or to embed --input-jsonl

    if checkpoint_path.exists():
        print(f"Found existing checkpoint at {checkpoint_path} -- loading it (training skipped).")
        model = MessageGraphSAGE()
        model.load_state_dict(torch.load(checkpoint_path, map_location="cpu"))
    else:
        model = bootstrap_checkpoint(checkpoint_path, embed_model, args.epochs, args.lr, args.pos_weight,
                                      args.weight_decay, args.patience)

    run_inference(model, args.input_jsonl, embed_model)


if __name__ == "__main__":
    main()
