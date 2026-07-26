"""
Full-pipeline validation report: unlike scripts/evaluate_validation.py (which
compares the GNN's raw conv_score >= 0.5 threshold against ground truth),
this runs the ENTIRE live pipeline per conversation -- preprocess -> embed
(precomputed here) -> graph -> GNN -> LLM reasoning, via
pipeline/inference.py::score_conversation() -- and compares the LLM's own
final conversation_label against ground truth. This is what actually ships
in backend/, so it's the real accuracy number; scripts/evaluate_validation.py
only tells you how good the GNN's number is before the LLM gets a chance to
override it.

Makes one real Anthropic API call per conversation -- NOT instant, NOT free.
Use --limit for a quick sanity check before running the full set.

Usage (run with pipeline/ as the working directory):
    cd pipeline
    python scripts/evaluate_with_llm.py \\
        --val-jsonl dataset/validation_new.jsonl \\
        --val-embeddings dataset/validation_new_embeddings.npz \\
        --checkpoint checkpoints/message_graph_sage_old.pt \\
        --limit 10
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # pipeline/ -- so train/gnn/inference resolve as siblings

from train import load_conversations, load_embeddings, per_class_stats, macro_f1  # noqa: E402
from gnn.conversation_gnn import MessageGraphSAGE  # noqa: E402
from inference import score_conversation  # noqa: E402

BINARY_FROM_LABEL = {"safe": 0, "harmful": 1}


def prepare_messages(conversation: dict, embeddings: dict) -> list:
    """Like evaluate_validation.py's prepare_scored_example, but this script
    doesn't need the GNN's own per-message scores separately -- score_conversation()
    computes and uses them internally as part of the full pipeline."""
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
    return messages


def run_conversation(conv: dict, embeddings: dict, model: MessageGraphSAGE) -> dict:
    conv_id = conv.get("conversation_id", "?")
    true_binary = 1 if conv["binary_conversation_label"] == "harmful" else 0
    harm_type = conv.get("conversation_label", "unknown")
    messages = prepare_messages(conv, embeddings)

    try:
        llm_result = score_conversation(conv_id, messages, model)
        predicted_label = llm_result.get("conversation_label")
        predicted_binary = BINARY_FROM_LABEL.get(predicted_label)
        if predicted_binary is None:
            raise ValueError(f"LLM returned unexpected conversation_label: {predicted_label!r}")
        return {
            "conversation_id": conv_id,
            "harm_type": harm_type,
            "true_binary": true_binary,
            "predicted_binary": predicted_binary,
            "predicted_label": predicted_label,
            "conversation_confidence": llm_result.get("conversation_confidence"),
            "severity": llm_result.get("severity"),
            "gentle_alert_text": llm_result.get("gentle_alert_text"),
            "top_evidence_messages": llm_result.get("top_evidence_messages", []),
            "correct": predicted_binary == true_binary,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001 -- one bad conversation (API error, bad JSON, etc.) must not kill the run
        return {
            "conversation_id": conv_id,
            "harm_type": harm_type,
            "true_binary": true_binary,
            "predicted_binary": None,
            "correct": False,
            "error": f"{type(e).__name__}: {e}",
        }


def print_report(results: list, checkpoint: str, val_jsonl: str):
    ok = [r for r in results if r["error"] is None]
    errors = [r for r in results if r["error"] is not None]

    print("\n=== LLM-Judged Validation Report ===")
    print(f"Checkpoint:      {checkpoint}")
    print(f"Validation set:  {val_jsonl}  ({len(results)} conversations attempted, {len(ok)} scored, {len(errors)} failed)")

    if errors:
        print(f"\n--- {len(errors)} conversation(s) failed to score ---")
        for r in errors[:10]:
            print(f"  {r['conversation_id']}: {r['error']}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more (see --output for full list)")

    if not ok:
        print("\nNo conversations scored successfully -- nothing to report.")
        return

    y_true = [r["true_binary"] for r in ok]
    y_pred = [r["predicted_binary"] for r in ok]
    label_name = {0: "safe", 1: "harmful"}

    print("\n--- Overall performance (LLM's final judgment vs. ground truth) ---")
    stats = per_class_stats(y_true, y_pred)
    for cls in (0, 1):
        s = stats[cls]
        print(f"  {label_name[cls]:8s}  precision={s['precision']:.4f}  recall={s['recall']:.4f}  "
              f"f1={s['f1']:.4f}  (tp={s['tp']} fp={s['fp']} fn={s['fn']})")
    print(f"  macro_f1={macro_f1(y_true, y_pred):.4f}")
    n_correct = sum(r["correct"] for r in ok)
    print(f"  accuracy={n_correct / len(ok):.4f}  ({n_correct}/{len(ok)} correct)")

    print("\n--- Breakdown by harm type (ground truth conversation_label) ---")
    by_type = defaultdict(list)
    for r in ok:
        by_type[r["harm_type"]].append(r)
    for harm_type in sorted(by_type, key=lambda t: (t != "safe", t)):
        group = by_type[harm_type]
        n = len(group)
        n_correct_group = sum(r["correct"] for r in group)
        verb = "predicted safe" if harm_type == "safe" else "predicted harmful"
        print(f"  {harm_type:14s}  n={n:<4d}  correctly {verb}: {n_correct_group}/{n} ({100 * n_correct_group / n:.1f}%)")

    print("\n--- Misclassified examples (LLM disagreed with ground truth) ---")
    wrong = [r for r in ok if not r["correct"]]
    if not wrong:
        print("  none.")
    else:
        for r in wrong[:15]:
            print(f"  [{r['harm_type']}] {r['conversation_id']}  LLM said {r['predicted_label']} "
                  f"(confidence={r['conversation_confidence']}) -- actually {label_name[r['true_binary']]}")
            print(f"      reasoning: {r.get('gentle_alert_text', '')}")
        if len(wrong) > 15:
            print(f"  ... and {len(wrong) - 15} more (see --output for full list)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--val-jsonl", default="dataset/validation.jsonl")
    parser.add_argument("--val-embeddings", required=True)
    parser.add_argument("--checkpoint", default="checkpoints/message_graph_sage_old.pt")
    parser.add_argument("--limit", type=int, default=None, help="only score the first N conversations (sanity check)")
    parser.add_argument("--output", default="llm_validation_report.json")
    args = parser.parse_args()

    print(f"Loading checkpoint from {args.checkpoint}...")
    model = MessageGraphSAGE()
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu"))
    model.eval()

    print(f"Loading {args.val_jsonl} + {args.val_embeddings}...")
    embeddings = load_embeddings(args.val_embeddings)
    conversations = load_conversations(args.val_jsonl)
    if args.limit:
        conversations = conversations[: args.limit]
    print(f"Scoring {len(conversations)} conversations via the full pipeline (one LLM call each)...")

    results = []
    for i, conv in enumerate(conversations):
        r = run_conversation(conv, embeddings, model)
        results.append(r)
        status = "OK" if r["error"] is None else f"FAILED ({r['error']})"
        print(f"  [{i + 1}/{len(conversations)}] {r['conversation_id']}: {status}")

    print_report(results, args.checkpoint, args.val_jsonl)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nFull per-conversation report written to: {args.output}")


if __name__ == "__main__":
    main()
