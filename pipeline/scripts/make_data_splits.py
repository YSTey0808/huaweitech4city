"""
Creates nested, stratified subsets of dataset/train.jsonl at 25%/50%/75%
sizes, for a learning-curve experiment: train at each size, plot val
macro-F1 against dataset size. If it's still climbing at 100%, the model
is data-limited -- collect more. If it's flattened, more data won't help
much and the bottleneck is elsewhere (features/architecture/label quality).

Stratification: binary_conversation_label is kept exactly 50/50 (safe /
harmful) in every subset -- that's the point of stratifying at all, so
size is the only thing varying between files, not class balance. Within
the harmful half, the 3 typed harm categories (scam/cyberbullying/
grooming) are split as equally as possible, scarcest first -- but
cyberbullying (77 total) and grooming (102 total) aren't plentiful enough
for perfectly equal three-way representation past ~58% of the dataset. Once
a category's pool is exhausted, the remainder of the harmful quota goes to
the next-scarcest category with room left (see the printed report for the
exact counts actually used per file -- don't assume equal thirds without
checking it).

Nested by construction: each category's pool is shuffled once (seeded),
then increasing-length prefixes are taken per fraction -- so the 25%
subset is a strict subset of the 50% subset, which is a strict subset of
the 75% subset.

--source itself is the 100% split (unchanged, no new file needed for it).
The corresponding validation file is never touched -- use it as the fixed
eval set across all four sizes so results are comparable.

Usage:
    python make_data_splits.py                                     # dataset/train.jsonl -> train_{25,50,75}pct.jsonl
    python make_data_splits.py --source dataset/train_new.jsonl     # -> train_new_{25,50,75}pct.jsonl
"""

import argparse
import json
import random
from pathlib import Path

FRACTIONS = [0.25, 0.50, 0.75]
SEED = 42
HARM_TYPES_SCARCEST_FIRST = ["cyberbullying", "grooming", "scam"]


def load(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write(path, convs):
    with open(path, "w") as f:
        for c in convs:
            f.write(json.dumps(c) + "\n")


def split_harmful_quota(target_harmful: int, available: dict) -> dict:
    """
    Divides target_harmful as equally as possible across
    HARM_TYPES_SCARCEST_FIRST, capping each at what's available and
    handing any resulting surplus down to the next category in line.
    """
    remaining = target_harmful
    counts = {}
    for i, ht in enumerate(HARM_TYPES_SCARCEST_FIRST):
        n_left = len(HARM_TYPES_SCARCEST_FIRST) - i
        want = remaining // n_left
        got = min(want, available[ht])
        counts[ht] = got
        remaining -= got
    if remaining > 0:
        # last category (scam, the least scarce) absorbs anything still left
        last = HARM_TYPES_SCARCEST_FIRST[-1]
        extra = min(remaining, available[last] - counts[last])
        counts[last] += extra
        remaining -= extra
    if remaining > 0:
        print(f"  WARNING: {remaining} harmful conversations short of target "
              f"-- ran out of data across all 3 harm types.")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="dataset/train.jsonl")
    args = parser.parse_args()
    source = args.source
    stem = Path(source).stem  # "train" -> train_25pct.jsonl; "train_new" -> train_new_25pct.jsonl

    convs = load(source)
    by_category = {"safe": [], "scam": [], "cyberbullying": [], "grooming": []}
    for c in convs:
        by_category[c["conversation_label"]].append(c)

    rng = random.Random(SEED)
    for pool in by_category.values():
        rng.shuffle(pool)

    total = len(convs)
    available = {k: len(v) for k, v in by_category.items()}
    print(f"Source: {source} ({total} conversations)")
    print(f"Available per category: {available}\n")

    for frac in FRACTIONS:
        target_total = round(frac * total)
        target_safe = target_total // 2
        target_harmful = target_total - target_safe

        counts = split_harmful_quota(target_harmful, available)
        counts["safe"] = min(target_safe, available["safe"])

        subset = []
        for cat, n in counts.items():
            subset.extend(by_category[cat][:n])
        rng.shuffle(subset)  # interleave categories rather than leaving them grouped in the file

        out_path = f"dataset/{stem}_{int(frac * 100)}pct.jsonl"
        write(out_path, subset)

        actual_total = len(subset)
        status = "exact" if actual_total == target_total else f"SHORT by {target_total - actual_total}"
        print(f"{out_path}: {actual_total} conversations (target {target_total}, {status})")
        print(f"  safe={counts['safe']}  scam={counts['scam']}  "
              f"cyberbullying={counts['cyberbullying']}  grooming={counts['grooming']}")
        binary_harmful = counts['scam'] + counts['cyberbullying'] + counts['grooming']
        print(f"  binary: safe={counts['safe']}  harmful={binary_harmful}\n")

    print(f"{source} itself is the 100% split -- no new file needed for it.")
    print("The corresponding validation file is untouched -- use it as the fixed eval set across all sizes.")


if __name__ == "__main__":
    main()
