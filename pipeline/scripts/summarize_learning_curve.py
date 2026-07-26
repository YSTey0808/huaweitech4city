"""
Aggregates a set of evaluate_validation.py JSON reports (one per training-set
size) into a single learning-curve summary: overall accuracy/macro-F1 and a
per-harm-type breakdown at each size, as CSV + JSON. Reuses train.py's
per_class_stats/macro_f1 -- one source of truth per metric, not
re-implemented here.

Usage:
    cd pipeline
    python scripts/summarize_learning_curve.py \\
        --report 25:reports/learning_curve/new_25pct_validation_report.json:319 \\
        --report 50:reports/learning_curve/new_50pct_validation_report.json:638 \\
        --report 75:reports/learning_curve/new_75pct_validation_report.json:957 \\
        --report 100:reports/new_dataset_validation_report.json:1276 \\
        --output reports/learning_curve/summary
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # pipeline/ -- so train resolves as a sibling

from train import per_class_stats, macro_f1  # noqa: E402


def summarize_one(report_path: str) -> dict:
    with open(report_path) as f:
        results = json.load(f)

    y_true = [r["true_binary"] for r in results]
    y_pred = [r["predicted_binary"] for r in results]
    stats = per_class_stats(y_true, y_pred)
    n_correct = sum(r["correct"] for r in results)

    by_type = defaultdict(list)
    for r in results:
        by_type[r["harm_type"]].append(r)
    harm_type_recall = {}
    for harm_type, group in by_type.items():
        n = len(group)
        n_correct_group = sum(r["correct"] for r in group)
        harm_type_recall[harm_type] = {"n": n, "n_correct": n_correct_group, "rate": n_correct_group / n}

    return {
        "n_val": len(results),
        "accuracy": n_correct / len(results),
        "macro_f1": macro_f1(y_true, y_pred),
        "safe_precision": stats[0]["precision"], "safe_recall": stats[0]["recall"], "safe_f1": stats[0]["f1"],
        "harmful_precision": stats[1]["precision"], "harmful_recall": stats[1]["recall"], "harmful_f1": stats[1]["f1"],
        "by_harm_type": harm_type_recall,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="append", required=True,
                         help="label:path_to_json:n_train_conversations, repeatable")
    parser.add_argument("--output", required=True, help="output path prefix -- writes <prefix>.csv and <prefix>.json")
    args = parser.parse_args()

    rows = []
    for spec in args.report:
        label, path, n_train = spec.split(":")
        row = {"split_label": label, "n_train": int(n_train), **summarize_one(path)}
        rows.append(row)
        print(f"{label}%  n_train={n_train}  accuracy={row['accuracy']:.4f}  macro_f1={row['macro_f1']:.4f}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(f"{out}.json", "w") as f:
        json.dump(rows, f, indent=2)

    harm_types = sorted({ht for r in rows for ht in r["by_harm_type"]})
    with open(f"{out}.csv", "w", newline="") as f:
        fieldnames = ["split_label", "n_train", "n_val", "accuracy", "macro_f1",
                      "safe_precision", "safe_recall", "safe_f1",
                      "harmful_precision", "harmful_recall", "harmful_f1"] + [f"{ht}_recall" for ht in harm_types]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            flat = {k: r[k] for k in fieldnames if k in r}
            for ht in harm_types:
                flat[f"{ht}_recall"] = r["by_harm_type"].get(ht, {}).get("rate", "")
            writer.writerow(flat)

    print(f"\nWrote {out}.json and {out}.csv")


if __name__ == "__main__":
    main()
