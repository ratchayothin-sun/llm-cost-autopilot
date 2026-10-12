"""Compare routing policies from the stored eval results. Makes no model calls.

Usage (from the project root):
    python -m eval.policy_analysis                # dev split (default)
    python -m eval.policy_analysis --split test   # only for the final report

"Oracle" cascades assume a PERFECT verifier (stop at the first correct tier) and
ignore the verifier's own cost, so they are an upper bound on what a real router
can achieve, not a result. If a later tier has not been run for some item, the
accuracy is shown as a range (missing = not rescued ... missing = rescued).
Costs are simulated from the reference prices in configs/models.yaml.
"""
import argparse
import json
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORDER = ["small", "medium", "large"]
MARK = {1: "ok", 0: "WRONG", None: "-"}


def load_items(dataset, split):
    items = {}
    with open(dataset, encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                it = json.loads(line)
                if split == "all" or it.get("split", "dev") == split:
                    items[it["id"]] = it.get("category", "?")
    return items


def load_results(db, ids):
    conn = sqlite3.connect(db)
    res = {}
    for item_id, tier, correct, cost in conn.execute(
        "SELECT item_id, tier, correct, cost FROM results WHERE error IS NULL"
    ):
        if item_id in ids:
            res.setdefault(item_id, {})[tier] = (int(correct), float(cost or 0.0))
    return res


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def tier_stats(tier, ids, res):
    rows = [res[i][tier] for i in ids if tier in res.get(i, {})]
    n = len(rows)
    k = sum(r[0] for r in rows)
    cost = sum(r[1] for r in rows) / n if n else 0.0
    return n, k, cost


def oracle(order, ids, res, est_cost):
    """Perfect-verifier cascade. Returns (n, solved, unknown, avg_cost)."""
    n = solved = unknown = 0
    total = 0.0
    for i in ids:
        r = res.get(i, {})
        if order[0] not in r:
            continue
        n += 1
        got_it = unk = False
        for t in order:
            if t not in r:
                unk = True
                total += est_cost[t]  # missing result: use the tier's mean cost
                break
            total += r[t][1]
            if r[t][0]:
                got_it = True
                break
        if got_it:
            solved += 1
        elif unk:
            unknown += 1
    return n, solved, unknown, (total / n if n else 0.0)


def fmt_acc(k, n, unknown=0):
    if n == 0:
        return "n/a"
    if unknown:
        return f"{100 * k / n:.0f}%-{100 * (k + unknown) / n:.0f}%"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% (CI {100 * lo:.0f}-{100 * hi:.0f})"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    parser.add_argument("--db", default=str(ROOT / "eval_results.db"))
    parser.add_argument("--dataset", default=str(ROOT / "dataset.jsonl"))
    parser.add_argument("--max-grid", type=int, default=40)
    args = parser.parse_args()

    items = load_items(args.dataset, args.split)
    ids = sorted(items)
    res = load_results(args.db, set(ids))

    print(f"split={args.split}: {len(ids)} items in dataset\n")
    print("=== Coverage and accuracy per tier (95% Wilson interval) ===")
    est = {}
    for t in ORDER:
        n, k, cost = tier_stats(t, ids, res)
        est[t] = cost
        print(f"{t:8} results {n:3}/{len(ids)}  acc {fmt_acc(k, n):24} avg_cost {cost:.6f}")

    print("\n=== Policies (cost = simulated, per request) ===")
    print(f"{'policy':36} {'items':>5}  {'accuracy':26} {'avg_cost':>10}  vs always-large")
    large_cost = est["large"] or 0.0

    def ratio(c):
        return f"{100 * c / large_cost:.0f}%" if large_cost else "n/a"

    partial = False
    for t in ORDER:
        n, k, cost = tier_stats(t, ids, res)
        if n:
            star = " *" if n < len(ids) else ""
            partial = partial or bool(star)
            print(f"{'always ' + t + star:36} {n:5}  {fmt_acc(k, n):26} {cost:10.6f}  {ratio(cost)}")

    for order in (["small", "medium"], ["small", "large"], ["small", "medium", "large"]):
        n, solved, unk, cost = oracle(order, ids, res, est)
        if n:
            star = " *" if n < len(ids) else ""
            partial = partial or bool(star)
            name = "oracle " + " > ".join(order) + star
            print(f"{name:36} {n:5}  {fmt_acc(solved, n, unk):26} {cost:10.6f}  {ratio(cost)}")
    if partial:
        print("  * covers only part of the items (a tier has not been run on all of them): "
              "not comparable with rows over all items. A 'large' row built mostly from "
              "small's failures is biased toward hard items.")

    # per-item grid for the items where small is wrong
    wrong = [i for i in ids if res.get(i, {}).get("small", (None,))[0] == 0]
    print(f"\n=== Items where small is wrong: {len(wrong)} "
          f"(ok = correct, WRONG = incorrect, - = not run) ===")
    print(f"{'id':8} {'category':12} {'small':6} {'medium':7} {'large':6}")
    for i in wrong[: args.max_grid]:
        r = res[i]
        cells = [MARK[r[t][0]] if t in r else MARK[None] for t in ORDER]
        print(f"{i:8} {items[i]:12} {cells[0]:6} {cells[1]:7} {cells[2]:6}")
    if len(wrong) > args.max_grid:
        print(f"... {len(wrong) - args.max_grid} more (use --max-grid)")

    rescued_m = sum(1 for i in wrong if res[i].get("medium", (0,))[0] == 1)
    rescued_l = sum(1 for i in wrong if res[i].get("large", (0,))[0] == 1)
    large_missing = sum(1 for i in wrong if "large" not in res[i])
    both_wrong = sum(
        1 for i in wrong
        if res[i].get("medium", (None,))[0] == 0 and res[i].get("large", (None,))[0] == 0
    )
    print(f"\nsmall wrong on {len(wrong)}: medium right on {rescued_m}, large right on {rescued_l}, "
          f"large not run on {large_missing}, medium and large both wrong on {both_wrong}")

    print("\nNotes:")
    print(" - Oracle rows assume a perfect verifier and ignore verifier cost: an upper bound.")
    print(" - A range like 70%-90% means some later-tier results are missing for those items.")
    print(" - Intervals overlap heavily at this sample size; do not report small gaps as real.")
    print(" - Costs are simulated from reference prices, not money spent.")
    if args.split != "test":
        print(" - Dev results guided the design of checks and prompts; report the test split once, at the end.")


if __name__ == "__main__":
    main()
