"""
Trains MessageGraphSAGE on labeled conversations.

Expects:
  - JSONL conversation files in the canonical schema (docs/data_schema.md):
    one conversation per line, with a "messages" list and a top-level
    "binary_conversation_label" ("harmful"/"safe"). README.md's documented
    layout is dataset/{train,validation}.jsonl (no held-out test split yet
    -- --test-jsonl/--test-embeddings are optional, see Usage below).
  - A separate embeddings file per split, mapping message_id -> vector.
    Format is auto-detected by extension in load_embeddings() below -- if
    your actual embeddings file doesn't match one of the supported shapes,
    that is the one function to edit; nothing else needs to change.

Only conversation-level labels are used (see docs/pipeline.md's "Evidence-
score derivation" section for why message-level labels aren't needed): the
same conv_head that scores the whole conversation, applied per-message
before pooling, already yields per-message evidence scores for free.

Trains one conversation per step (not batched across conversations) via
MessageGraphSAGE.forward_full -- the training/cold-start path, never
ConversationGraphState (that class is inference-only, see its docstring).
Simple and correct; batching multiple conversations into one forward pass
would need forward_full to pool with torch_geometric.nn.global_mean_pool
against a per-node batch vector instead of a plain mean(dim=0) -- worth
doing if training throughput becomes a bottleneck, not implemented here.

Usage:
    python train.py \\
        --train-embeddings path/to/train_embeddings.<ext> \\
        --val-embeddings path/to/val_embeddings.<ext>
    (--test-jsonl/--test-embeddings are optional; test evaluation is skipped
    if not both provided.)
"""

import argparse
import json
import pickle
import random
from pathlib import Path

import numpy as np
import torch
from torch.optim import AdamW

from gnn.conversation_gnn import build_message_graph, MessageGraphSAGE


def load_conversations(jsonl_path: str) -> list:
    conversations = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                conversations.append(json.loads(line))
    return conversations


def load_embeddings(path: str) -> dict:
    """
    Loads message embeddings into a dict: message_id -> FloatTensor[EMBED_DIM].
    Auto-detects by file extension. If your actual embeddings file doesn't
    match one of these shapes, edit this function -- nothing else in this
    script needs to know how embeddings are stored.

    Supported today:
      .json          {message_id: [floats...], ...}
                     or [{"message_id": ..., "embedding": [floats...]}, ...]
      .jsonl         one {"message_id": ..., "embedding": [floats...]} object per line
      .pkl/.pickle   a dict {message_id: array-like}, or a pandas DataFrame
                     with "message_id" and "embedding" columns
      .npz           two arrays, row-aligned: "message_id" (or "ids") and
                     "embedding" (or "vectors")
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".json":
        with open(path) as f:
            raw = json.load(f)
        items = raw.items() if isinstance(raw, dict) else ((r["message_id"], r["embedding"]) for r in raw)
        return {mid: torch.tensor(vec, dtype=torch.float32) for mid, vec in items}

    if suffix == ".jsonl":
        out = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    out[r["message_id"]] = torch.tensor(r["embedding"], dtype=torch.float32)
        return out

    if suffix in (".pkl", ".pickle"):
        with open(path, "rb") as f:
            raw = pickle.load(f)
        if isinstance(raw, dict):
            return {mid: torch.tensor(vec, dtype=torch.float32) for mid, vec in raw.items()}
        return {  # assume a pandas DataFrame with message_id / embedding columns
            row["message_id"]: torch.tensor(row["embedding"], dtype=torch.float32)
            for _, row in raw.iterrows()
        }

    if suffix == ".npz":
        raw = np.load(path, allow_pickle=True)
        ids = raw["message_id"] if "message_id" in raw else raw["ids"]
        vecs = raw["embedding"] if "embedding" in raw else raw["vectors"]
        return {mid: torch.tensor(vec, dtype=torch.float32) for mid, vec in zip(ids, vecs)}

    raise ValueError(
        f"Don't know how to load embeddings from '{path}' (unrecognized extension "
        f"'{suffix}'). Edit load_embeddings() in train.py to match your actual format."
    )


def prepare_example(conversation: dict, embeddings: dict):
    """
    Converts one raw conversation dict (canonical schema) + the embeddings
    lookup into (messages, label): the shape build_message_graph() expects,
    plus the ground-truth conversation-level target. Raises loudly on a
    missing embedding rather than silently skipping/zero-filling a message.
    """
    messages = []
    for m in conversation["messages"]:
        if m["message_id"] not in embeddings:
            raise KeyError(f'no embedding found for message_id={m["message_id"]!r}')
        messages.append({
            "message_id": m["message_id"],
            "sender_id": m["sender_id"],
            "embedding": embeddings[m["message_id"]],
            "reply_to_message_id": m.get("reply_to_message_id"),
        })
    label = 1.0 if conversation["binary_conversation_label"] == "harmful" else 0.0
    return messages, label


def per_class_stats(y_true: list, y_pred: list) -> dict:
    """Precision/recall/F1 per class (0=safe, 1=harmful) plus confusion
    counts -- the detail behind the single macro_f1() number below."""
    stats = {}
    for cls in (0, 1):
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p == cls)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != cls and p == cls)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p != cls)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        stats[cls] = {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}
    return stats


def macro_f1(y_true: list, y_pred: list) -> float:
    """Hand-rolled macro-F1 for binary 0/1 labels (avoids adding sklearn as
    a dependency for one metric); matches docs/data_schema.md's eval metric."""
    stats = per_class_stats(y_true, y_pred)
    return sum(s["f1"] for s in stats.values()) / len(stats)


def train_epoch(model, examples, optimizer, pos_weight: float) -> float:
    model.train()
    bce = torch.nn.BCELoss(reduction="none")
    random.shuffle(examples)
    total_loss = 0.0
    for messages, label in examples:
        optimizer.zero_grad()
        graph = build_message_graph(messages)
        conv_score, _ = model.forward_full(graph)
        target = torch.tensor([label])
        loss = bce(conv_score, target)
        loss = loss * (pos_weight if label == 1.0 else 1.0)  # upweight the minority "harmful" class
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(examples)


@torch.no_grad()
def predict_all(model, examples, threshold: float = 0.5):
    model.eval()
    y_true, y_pred = [], []
    for messages, label in examples:
        graph = build_message_graph(messages)
        conv_score, _ = model.forward_full(graph)
        y_true.append(int(label))
        y_pred.append(int(conv_score.item() >= threshold))
    return y_true, y_pred


def evaluate(model, examples, threshold: float = 0.5) -> float:
    y_true, y_pred = predict_all(model, examples, threshold)
    return macro_f1(y_true, y_pred)


def print_validation_report(model, examples, threshold: float = 0.5):
    """The distinct, clearly-labeled 'run the validation set over the
    trained model' step -- same predictions as evaluate(), but broken down
    per class instead of collapsed into one macro-F1 number."""
    y_true, y_pred = predict_all(model, examples, threshold)
    stats = per_class_stats(y_true, y_pred)
    label_name = {0: "safe", 1: "harmful"}
    print(f"\nValidation report ({len(examples)} conversations):")
    for cls in (0, 1):
        s = stats[cls]
        print(f"  {label_name[cls]:8s}  precision={s['precision']:.4f}  recall={s['recall']:.4f}  "
              f"f1={s['f1']:.4f}  (tp={s['tp']} fp={s['fp']} fn={s['fn']})")
    print(f"  macro_f1={sum(s['f1'] for s in stats.values()) / len(stats):.4f}")


def train_model(train_examples, val_examples, epochs: int, lr: float, pos_weight: float, checkpoint_path,
                 weight_decay: float = 1e-4, patience: int = None) -> MessageGraphSAGE:
    """
    The actual training loop, factored out of main() so other entry points
    (e.g. pipeline.py's train-if-no-checkpoint-exists path) can reuse it
    without going through argparse/CLI. Saves to checkpoint_path on every
    new best val_macro_f1, then reloads that best checkpoint before
    returning -- the returned model is always the best-val epoch, never
    whatever the last epoch happened to be.

    Regularization knobs (see MessageGraphSAGE.__init__ for dropout, applied
    inside the model itself): weight_decay uses AdamW, not plain Adam --
    Adam's L2 term doesn't decouple correctly from its adaptive per-parameter
    learning rate (Loshchilov & Hutter, "Decoupled Weight Decay
    Regularization"), so AdamW is the correct choice whenever weight decay
    is actually wanted, not just a style preference. patience is optional
    (None = disabled, matching the original always-run-all-epochs behavior)
    -- if set, training stops once `patience` epochs pass with no new best
    val_macro_f1, since after that point every epoch is only deepening
    memorization (see docs/pipeline.md's Known Limitations).
    """
    model = MessageGraphSAGE()
    optimizer = AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    checkpoint_path = Path(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    best_val_f1 = -1.0
    epochs_since_best = 0
    for epoch in range(1, epochs + 1):
        train_loss = train_epoch(model, train_examples, optimizer, pos_weight)
        val_f1 = evaluate(model, val_examples)
        marker = ""
        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            epochs_since_best = 0
            torch.save(model.state_dict(), checkpoint_path)
            marker = "  <- new best, saved"
        else:
            epochs_since_best += 1
        print(f"epoch {epoch:3d}  train_loss={train_loss:.4f}  val_macro_f1={val_f1:.4f}{marker}")

        if patience is not None and epochs_since_best >= patience:
            print(f"  no improvement in {patience} epochs, stopping early at epoch {epoch}")
            break

    print(f"\nLoading best checkpoint (val_macro_f1={best_val_f1:.4f})...")
    model.load_state_dict(torch.load(checkpoint_path))
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-jsonl", default="dataset/train.jsonl")
    parser.add_argument("--val-jsonl", default="dataset/validation.jsonl")
    parser.add_argument("--test-jsonl", default=None, help="optional -- skipped if not provided")
    parser.add_argument("--train-embeddings", required=True)
    parser.add_argument("--val-embeddings", required=True)
    parser.add_argument("--test-embeddings", default=None, help="optional -- skipped if not provided")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--pos-weight", type=float, default=1.0,
                         help="loss multiplier for 'harmful' examples, to counter class imbalance")
    parser.add_argument("--weight-decay", type=float, default=1e-4,
                         help="AdamW weight decay -- regularization against the small dataset size")
    parser.add_argument("--patience", type=int, default=None,
                         help="stop early after this many epochs with no new best val_macro_f1 "
                              "(default: disabled, always runs all --epochs)")
    parser.add_argument("--checkpoint", default="checkpoints/message_graph_sage_old.pt")
    args = parser.parse_args()

    print("Loading conversations and embeddings...")
    train_examples = [
        prepare_example(c, load_embeddings(args.train_embeddings))
        for c in load_conversations(args.train_jsonl)
    ]
    val_examples = [
        prepare_example(c, load_embeddings(args.val_embeddings))
        for c in load_conversations(args.val_jsonl)
    ]
    print(f"  train={len(train_examples)} conversations, val={len(val_examples)} conversations")

    model = train_model(train_examples, val_examples, args.epochs, args.lr, args.pos_weight, args.checkpoint,
                         weight_decay=args.weight_decay, patience=args.patience)

    print_validation_report(model, val_examples)

    if args.test_jsonl and args.test_embeddings:
        test_examples = [
            prepare_example(c, load_embeddings(args.test_embeddings))
            for c in load_conversations(args.test_jsonl)
        ]
        test_f1 = evaluate(model, test_examples)
        print(f"\ntest_macro_f1={test_f1:.4f}")


if __name__ == "__main__":
    main()
