"""Offline replay of routing policies on stored eval results. No API calls, no cost.

Every tier already answered every dev item (python -m eval.run_eval), so a policy
can be replayed by looking up the stored answer of whichever tier it would have
called, and adding up that tier's stored cost and latency.

    python -m eval.replay                      # dev split (default)
    python -m eval.replay --auto-classify      # also try a prompt-only task classifier (needs scikit-learn)
    python -m eval.replay --split test         # only for the final report, once

Costs are simulated from reference prices, not money spent. Latency is the sum
of the calls a policy makes one after another; the agreement policy runs the
small and medium calls in parallel.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from math import comb, sqrt
from pathlib import Path

from app.router import verifiers
from app.router.policy import POLICIES, plan_tiers

HERE = Path(__file__).resolve().parent
TIERS = ["small", "medium", "large"]


# ------------------------------------------------------------------ loading

def load_dataset(path):
    items = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            it.setdefault("split", "dev")
            items[it["id"]] = it
    return items


def load_results(db_path, dataset, split):
    """{item_id: {"category", "prompt", "tiers": {tier: row}}} for items that have a
    stored, error-free result in all three tiers. Also returns the ids left out."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT item_id, tier, output, correct, cost, latency, error FROM results").fetchall()
    con.close()

    per_item = {}
    for r in rows:
        it = dataset.get(r["item_id"])
        if it is None or (split != "all" and it["split"] != split):
            continue
        if r["error"] or r["correct"] is None:
            continue
        entry = per_item.setdefault(r["item_id"], {
            "id": r["item_id"], "category": it["category"], "prompt": it["prompt"], "tiers": {}})
        entry["tiers"][r["tier"]] = {
            "output": r["output"] or "", "correct": int(r["correct"]),
            "cost": float(r["cost"] or 0.0), "latency": float(r["latency"] or 0.0)}

    wanted = [i for i, it in dataset.items() if split == "all" or it["split"] == split]
    complete = {i: e for i, e in per_item.items() if all(t in e["tiers"] for t in TIERS)}
    skipped = [i for i in wanted if i not in complete]
    return complete, skipped


# ------------------------------------------------------------------- policies
# A policy maps an item to (final_tier, cost, latency).

def run_plan(item, plan, accept):
    """Call the planned tiers in order until accept(tier, row) is true; the last tier is kept."""
    cost = latency = 0.0
    for k, name in enumerate(plan):
        row = item["tiers"][name]
        cost += row["cost"]
        latency += row["latency"]
        if k == len(plan) - 1 or accept(name, row):
            return name, cost, latency


def always(tier):
    return lambda item: run_plan(item, [tier], lambda *_: True)


def gateway_policy(policy, task_type_of):
    """The exact policy the gateway would run (app/router/policy.py)."""
    verify = verifiers.VERIFIERS[policy.verifier]

    def run(item):
        plan = plan_tiers(policy, task_type_of(item), TIERS)
        messages = [{"role": "user", "content": item["prompt"]}]
        return run_plan(item, plan, lambda _t, row: bool(verify(messages, row["output"])))
    return run


def oracle(plan):
    """Perfect verifier (uses the gold label). A ceiling: real verifiers cost extra and err."""
    return lambda item: run_plan(item, plan, lambda _t, row: bool(row["correct"]))


def omniscient_router(item):
    """Knows in advance the cheapest correct tier and calls only that one."""
    for name in TIERS:
        if item["tiers"][name]["correct"]:
            row = item["tiers"][name]
            return name, row["cost"], row["latency"]
    row = item["tiers"]["large"]
    return "large", row["cost"], row["latency"]


def agreement(item):
    """Call small and medium in parallel. If their answers match, keep medium's; otherwise
    (different, or too free-form to compare) ask large as well."""
    small, medium, large = (item["tiers"][t] for t in TIERS)
    cost = small["cost"] + medium["cost"]
    latency = max(small["latency"], medium["latency"])
    if verifiers.answers_agree(small["output"], medium["output"]) is True:
        return "medium", cost, latency
    return "large", cost + large["cost"], latency + large["latency"]


# ------------------------------------------------------------- statistics

def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def sign_test_p(wins, losses):
    """Two-sided exact binomial (sign) test on the items where two policies differ."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def evaluate(policy, items):
    """{item_id: (tier, correct, cost, latency)} for a policy over items."""
    out = {}
    for iid, item in items.items():
        tier, cost, latency = policy(item)
        out[iid] = (tier, item["tiers"][tier]["correct"], cost, latency)
    return out


# ------------------------------------------------------- optional classifier

def auto_task_types(dataset, target_ids):
    """Predict a task_type for each target item from its prompt text alone.
    Items in dev get a leave-one-out prediction (the model never sees their own label);
    other items are predicted by a model trained on all dev prompts."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    dev = [it for it in dataset.values() if it["split"] == "dev"]
    predictions = {}
    for iid in target_ids:
        train = [it for it in dev if it["id"] != iid]
        model = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3), sublinear_tf=True),
            LogisticRegression(C=10, max_iter=2000))
        model.fit([it["prompt"] for it in train], [it["category"] for it in train])
        predictions[iid] = model.predict([dataset[iid]["prompt"]])[0]
    return predictions


# --------------------------------------------------------------------- report

def verifier_diagnostics(items):
    print("=== format_rules as a verifier, per tier (what it would reject) ===")
    print(f"{'tier':8s} {'rejects wrong':>14s} {'rejects right':>14s} {'accepts wrong':>14s} {'accepts right':>14s}")
    for tier in TIERS:
        c = Counter()
        for item in items.values():
            row = item["tiers"][tier]
            ok = verifiers.format_rules(item["prompt"], row["output"]).accept
            c[("accept" if ok else "reject", "right" if row["correct"] else "wrong")] += 1
        print(f"{tier:8s} {c[('reject', 'wrong')]:14d} {c[('reject', 'right')]:14d} "
              f"{c[('accept', 'wrong')]:14d} {c[('accept', 'right')]:14d}")
    print()


def agreement_diagnostics(items):
    c = Counter()
    for item in items.values():
        a = verifiers.answers_agree(item["tiers"]["small"]["output"], item["tiers"]["medium"]["output"])
        med = "medium right" if item["tiers"]["medium"]["correct"] else "medium wrong"
        c[("undecidable" if a is None else "agree" if a else "disagree", med)] += 1
    print("=== small vs medium answers: agree / disagree / undecidable ===")
    for key in sorted(c):
        print(f"  {key[0]:12s} {key[1]:13s} {c[key]:3d}")
    print()


def print_report(items, policies, baseline="always medium"):
    results = {name: evaluate(fn, items) for name, fn in policies.items()}
    n = len(items)
    large_cost = sum(v[2] for v in results["always large"].values()) / n
    base = results[baseline]

    print(f"{'policy':36s} {'accuracy (95% CI)':22s} {'cost':>9s} {'vs large':>8s} {'latency':>8s}   vs {baseline}")
    for name, res in results.items():
        k = sum(v[1] for v in res.values())
        lo, hi = wilson(k, n)
        cost = sum(v[2] for v in res.values()) / n
        lat = sum(v[3] for v in res.values()) / n
        wins = sum(1 for i in res if res[i][1] and not base[i][1])
        losses = sum(1 for i in res if base[i][1] and not res[i][1])
        versus = "" if name == baseline else f"+{wins} / -{losses}  p={sign_test_p(wins, losses):.2f}"
        print(f"{name:36s} {k / n:5.1%} ({lo:4.0%}-{hi:4.0%})      {cost:9.6f} {cost / large_cost:8.0%} {lat:7.1f}s   {versus}")
    print()
    return results


def print_wrong(items, results, names=("always medium", "always large", "router (true task_type)")):
    """List the items each of a few policies gets wrong (to audit checkers, not to tune policies)."""
    print("=== Items each policy gets wrong ===")
    for name in names:
        if name in results:
            wrong = sorted(i for i in items if not results[name][i][1])
            print(f"{name:26s} ({len(wrong):2d}): {' '.join(wrong) if wrong else '-'}")
    print()


def build_policies(task_types=None):
    by_category = lambda item: item["category"]  # noqa: E731  (true label: an upper bound for a classifier)
    policies = {
        "always small": always("small"),
        "always medium": always("medium"),
        "always large": always("large"),
        "cascade (nonempty verifier)": gateway_policy(POLICIES["cascade"], by_category),
        "cascade_format": gateway_policy(POLICIES["cascade_format"], by_category),
        "router (true task_type)": gateway_policy(POLICIES["router"], by_category),
    }
    if task_types is not None:
        policies["router (auto task_type, LOO)"] = gateway_policy(
            POLICIES["router"], lambda item: task_types[item["id"]])
    policies.update({
        "agreement small+medium, else large": agreement,
        "CEILING oracle medium>large": oracle(["medium", "large"]),
        "CEILING oracle small>medium>large": oracle(TIERS),
        "CEILING omniscient router": omniscient_router,
    })
    return policies


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(HERE / "eval_results.db"))
    ap.add_argument("--dataset", default=str(HERE / "dataset.jsonl"))
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--auto-classify", action="store_true",
                    help="also route by a task_type predicted from the prompt (needs scikit-learn)")
    args = ap.parse_args(argv)

    # sqlite3.connect() silently creates an empty file when the path is wrong, so check first
    if not Path(args.dataset).is_file():
        print(f"cannot find the dataset at {args.dataset}")
        return 1
    if not Path(args.db).is_file():
        print(f"cannot find the results database at {args.db}\n"
              "It is not in a fresh clone (*.db is git-ignored unless added with git add -f). "
              "Either run python -m eval.run_eval for every tier to create it, or pass the file "
              "with --db.")
        return 1

    dataset = load_dataset(args.dataset)
    try:
        items, skipped = load_results(args.db, dataset, args.split)
    except sqlite3.DatabaseError as e:   # not a database, or no 'results' table
        print(f"{args.db} is not a usable results database ({e}). "
              "Re-create it with python -m eval.run_eval.")
        return 1
    print(f"split={args.split}: {len(items)} items with results from all three tiers"
          + (f", {len(skipped)} left out (missing or errored): {', '.join(skipped[:12])}"
             + (" ..." if len(skipped) > 12 else "") if skipped else ""))
    if not items:
        print("nothing to replay: run python -m eval.run_eval for every tier first")
        return 1
    print()

    task_types = None
    if args.auto_classify:
        try:
            task_types = auto_task_types(dataset, list(items))
        except ImportError:
            print("scikit-learn is not installed (pip install scikit-learn): skipping --auto-classify\n")
        else:
            right = sum(task_types[i] == items[i]["category"] for i in items)
            print("task classifier (prompt text only; dev items are predicted leave-one-out, "
                  "other items by a model fit on all dev prompts): "
                  f"{right}/{len(items)} categories predicted correctly\n")

    print("=== Policies (cost = simulated, per request; CEILING rows are not achievable) ===")
    results = print_report(items, build_policies(task_types))
    print_wrong(items, results)
    verifier_diagnostics(items)
    agreement_diagnostics(items)

    print("Notes:")
    print(" - '+W / -L' counts items where the policy is right and always-medium wrong (W) or the reverse (L);")
    print("   p is the exact two-sided sign test on those items. Small n: treat p as a rough guide only.")
    print(" - The ROUTES table (app/router/policy.py) was chosen after reading dev results: in-sample.")
    print(" - 'router (true task_type)' uses the gold category; a real gateway needs the client to send")
    print("   task_type or a classifier to guess it (--auto-classify shows how well that works).")
    print(" - Dev results also guided the checkers and prompts. Report the test split once, at the end.")
    print(" - Costs are simulated from reference prices, not money spent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
