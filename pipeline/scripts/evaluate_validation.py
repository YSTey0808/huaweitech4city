"""
Full validation-set report: runs a trained checkpoint over a validation
split and reports not just the overall macro-F1 (train.py's
print_validation_report already does that) but a breakdown by harm TYPE
(the typed conversation_label ground truth -- scam/cyberbullying/grooming/
safe -- which the model itself never sees, since it's trained binary; see
docs/data_schema.md) and a list of every misclassified conversation with
its top evidence message, so you can actually see what went wrong and
where.

Reuses train.py's load_conversations/load_embeddings/per_class_stats/
macro_f1 rather than re-implementing them -- one source of truth per
metric, matching this repo's existing convention (see
scripts/run_batch_pipeline.py's docstring).

Usage (run with pipeline/ as the working directory):
    cd pipeline
    python scripts/evaluate_validation.py \\
        --val-jsonl dataset/validation.jsonl \\
        --val-embeddings dataset/validation_embeddings.npz \\
        --checkpoint checkpoints/message_graph_sage_old.pt
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # pipeline/ -- so gnn/train resolve as siblings

from train import load_conversations, load_embeddings, per_class_stats, macro_f1  # noqa: E402
from gnn.config import TOP_K_EVIDENCE  # noqa: E402
from gnn.conversation_gnn import build_message_graph, MessageGraphSAGE  # noqa: E402


def prepare_scored_example(conversation: dict, embeddings: dict) -> dict:
    """Like train.py's prepare_example, but keeps everything a report needs
    that the training path doesn't: message text (for evidence display) and
    the typed conversation_label (for the harm-type breakdown) -- neither is
    used by the model itself, only by this report."""
    messages = []
    for m in conversation["messages"]:
        if m["message_id"] not in embeddings:
            raise KeyError(f'no embedding found for message_id={m["message_id"]!r}')
        messages.append({
            "message_id": m["message_id"],
            "sender_id": m["sender_id"],
            "text": m.get("content", ""),
            "embedding": embeddings[m["message_id"]],
            "reply_to_message_id": m.get("reply_to_message_id"),
        })
    return {
        "conversation_id": conversation.get("conversation_id", "?"),
        "messages": messages,
        "true_binary": 1 if conversation["binary_conversation_label"] == "harmful" else 0,
        "harm_type": conversation.get("conversation_label", "unknown"),
    }


@torch.no_grad()
def run_predictions(model: MessageGraphSAGE, examples: list, threshold: float) -> list:
    model.eval()
    results = []
    for ex in examples:
        graph = build_message_graph(ex["messages"])
        conv_score, per_message_scores = model.forward_full(graph)
        score = conv_score.item()
        predicted = int(score >= threshold)

        top_evidence = sorted(
            zip(ex["messages"], per_message_scores.tolist()),
            key=lambda pair: pair[1],
            reverse=True,
        )[:TOP_K_EVIDENCE]

        results.append({
            "conversation_id": ex["conversation_id"],
            "harm_type": ex["harm_type"],
            "true_binary": ex["true_binary"],
            "predicted_binary": predicted,
            "score": score,
            "correct": predicted == ex["true_binary"],
            "top_evidence": [
                {"message_id": m["message_id"], "text": m["text"], "score": s} for m, s in top_evidence
            ],
        })
    return results


def print_report(results: list, checkpoint: str, val_jsonl: str, threshold: float, show_examples: int):
    y_true = [r["true_binary"] for r in results]
    y_pred = [r["predicted_binary"] for r in results]
    label_name = {0: "safe", 1: "harmful"}

    print("=== Validation Report ===")
    print(f"Checkpoint:      {checkpoint}")
    print(f"Validation set:  {val_jsonl}  ({len(results)} conversations)")
    print(f"Threshold:       {threshold}")

    print("\n--- Overall performance ---")
    stats = per_class_stats(y_true, y_pred)
    for cls in (0, 1):
        s = stats[cls]
        print(f"  {label_name[cls]:8s}  precision={s['precision']:.4f}  recall={s['recall']:.4f}  "
              f"f1={s['f1']:.4f}  (tp={s['tp']} fp={s['fp']} fn={s['fn']})")
    print(f"  macro_f1={macro_f1(y_true, y_pred):.4f}")
    n_correct = sum(r["correct"] for r in results)
    print(f"  accuracy={n_correct / len(results):.4f}  ({n_correct}/{len(results)} correct)")

    print("\n--- Breakdown by harm type (ground truth conversation_label) ---")
    by_type = defaultdict(list)
    for r in results:
        by_type[r["harm_type"]].append(r)
    for harm_type in sorted(by_type, key=lambda t: (t != "safe", t)):
        group = by_type[harm_type]
        n = len(group)
        n_correct_group = sum(r["correct"] for r in group)
        if harm_type == "safe":
            fps = n - n_correct_group
            print(f"  {harm_type:14s}  n={n:<4d}  correctly predicted safe: {n_correct_group}/{n} "
                  f"({100 * n_correct_group / n:.1f}%)   false positives: {fps}")
        else:
            missed = n - n_correct_group
            print(f"  {harm_type:14s}  n={n:<4d}  correctly predicted harmful: {n_correct_group}/{n} "
                  f"({100 * n_correct_group / n:.1f}%)   missed: {missed}")

    print("\n--- Misclassified examples ---")
    wrong = [r for r in results if not r["correct"]]
    if not wrong:
        print("  none -- every conversation in the validation set was classified correctly.")
    else:
        wrong_by_type = defaultdict(list)
        for r in wrong:
            wrong_by_type[r["harm_type"]].append(r)
        for harm_type in sorted(wrong_by_type, key=lambda t: (t != "safe", t)):
            group = wrong_by_type[harm_type]
            print(f"\n  [{harm_type}] {len(group)} misclassified:")
            for r in group[:show_examples]:
                predicted_name = label_name[r["predicted_binary"]]
                true_name = label_name[r["true_binary"]]
                print(f"    {r['conversation_id']}  predicted={predicted_name} (score={r['score']:.4f})  "
                      f"actually={true_name}")
                for e in r["top_evidence"][:2]:
                    text = e["text"][:80] + ("..." if len(e["text"]) > 80 else "")
                    print(f"        evidence (score={e['score']:.2f}): \"{text}\"")
            if len(group) > show_examples:
                print(f"    ... and {len(group) - show_examples} more (see --output for the full list)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--val-jsonl", default="dataset/validation.jsonl")
    parser.add_argument("--val-embeddings", required=True)
    parser.add_argument("--checkpoint", default="checkpoints/message_graph_sage_old.pt")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--show-examples", type=int, default=5,
                         help="max misclassified examples printed per harm type (full list still in --output)")
    parser.add_argument("--output", default="validation_report.json",
                         help="where to write the full per-conversation JSON report; pass '' to skip writing one")
    args = parser.parse_args()

    print(f"Loading checkpoint from {args.checkpoint}...")
    model = MessageGraphSAGE()
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu"))

    print(f"Loading {args.val_jsonl} + {args.val_embeddings}...")
    embeddings = load_embeddings(args.val_embeddings)
    examples = [prepare_scored_example(c, embeddings) for c in load_conversations(args.val_jsonl)]

    results = run_predictions(model, examples, args.threshold)
    print_report(results, args.checkpoint, args.val_jsonl, args.threshold, args.show_examples)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nFull per-conversation report written to: {args.output}")


if __name__ == "__main__":
    main()
