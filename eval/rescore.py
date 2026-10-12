"""Recompute the 'correct' flag of stored results with the CURRENT checker. No model calls.

Use it after a checker fix (the model outputs are stored, so nothing needs to be re-run):

    python -m eval.rescore --dry-run    # list the rows that would change
    python -m eval.rescore              # backup the database, then update

Only rows without an error are rescored. Rows whose item prompt was changed must be
re-run instead (eval.apply_fixes deletes those rows for you).
"""
import argparse
import json
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

from eval.run_eval import check_answer

ROOT = Path(__file__).resolve().parent


def load_items(path):
    items = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                it = json.loads(line)
                items[it["id"]] = it
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "eval_results.db"))
    ap.add_argument("--dataset", default=str(ROOT / "dataset.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    items = load_items(args.dataset)
    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT item_id, tier, output, correct FROM results WHERE error IS NULL"
    ).fetchall()

    changes, unknown = [], 0
    before, after = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for item_id, tier, output, old in rows:
        item = items.get(item_id)
        if item is None:
            unknown += 1
            continue
        new = int(check_answer(output or "", item["check"]))
        before[tier][0] += int(old)
        before[tier][1] += 1
        after[tier][0] += new
        after[tier][1] += 1
        if new != int(old):
            changes.append((item_id, tier, int(old), new, output or ""))

    print(f"{len(rows)} stored results checked"
          + (f", {unknown} skipped (item no longer in the dataset)" if unknown else ""))
    if not changes:
        print("no result changes with the current checker")
        return
    print(f"\n{len(changes)} result(s) change:")
    for item_id, tier, old, new, output in sorted(changes):
        tail = output.strip().replace("\n", " ⏎ ")[-90:]
        print(f"  {item_id:7} {tier:7} {'ok' if old else 'WRONG'} -> {'ok' if new else 'WRONG'}   {tail}")
    print("\naccuracy per tier (errors excluded):")
    for tier in sorted(before):
        b, a = before[tier], after[tier]
        print(f"  {tier:7} {b[0]}/{b[1]} -> {a[0]}/{a[1]}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return
    backup = Path(args.db).with_name("eval_results_pre_rescore.db")
    conn.close()
    shutil.copy(args.db, backup)
    conn = sqlite3.connect(args.db)
    for item_id, tier, _, new, _ in changes:
        conn.execute("UPDATE results SET correct=? WHERE item_id=? AND tier=?", (new, item_id, tier))
    conn.commit()
    conn.close()
    print(f"\nupdated {len(changes)} rows (backup: {backup.name})")


if __name__ == "__main__":
    main()
