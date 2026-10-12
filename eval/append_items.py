"""Validate eval/round3.jsonl and append it to eval/dataset.jsonl safely.

Usage (from the project root):
    python -m eval.append_items --dry-run     # check only, writes nothing
    python -m eval.append_items               # backup + append

Safe against the problem we hit before: if dataset.jsonl does not end with a
newline, the first new item is NOT glued onto the last old line.
"""
import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALID_CHECKS = {"number", "contains_any", "json_keys", "regex"}


def read_jsonl(path):
    items = []
    with open(path, encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    items.append((n, json.loads(line)))
                except json.JSONDecodeError as e:
                    print(f"{path.name} line {n}: invalid JSON ({e})")
                    sys.exit(1)
    return items


def validate(new_items, existing_ids):
    problems = []
    seen = set()
    for n, it in new_items:
        tag = f"line {n} ({it.get('id', '?')})"
        for key in ("id", "category", "split", "prompt", "check"):
            if key not in it:
                problems.append(f"{tag}: missing '{key}'")
        if problems and "check" not in it:
            continue
        if it["id"] in existing_ids:
            problems.append(f"{tag}: id already in dataset.jsonl")
        if it["id"] in seen:
            problems.append(f"{tag}: duplicate id inside the new file")
        seen.add(it["id"])
        if it["split"] not in ("dev", "test"):
            problems.append(f"{tag}: split must be 'dev' or 'test'")
        check = it["check"]
        kind = check.get("type")
        if kind not in VALID_CHECKS:
            problems.append(f"{tag}: unknown check type {kind!r}")
            continue
        if kind == "regex":
            try:
                re.compile(check["pattern"])
            except re.error as e:
                problems.append(f"{tag}: bad regex ({e})")
        if kind == "contains_any":
            for v in check["values"]:
                if v.lower() in it["prompt"].lower():
                    problems.append(f"{tag}: expected answer {v!r} appears in the prompt")
        if kind == "json_keys":
            for k in check.get("expect", {}):
                if k not in check["keys"]:
                    problems.append(f"{tag}: expect key {k!r} not in keys")
        if kind == "number" and not isinstance(check.get("value"), (int, float)):
            problems.append(f"{tag}: number check needs a numeric value")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new", default=str(ROOT / "round3.jsonl"))
    parser.add_argument("--dataset", default=str(ROOT / "dataset.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    new_path, data_path = Path(args.new), Path(args.dataset)
    if not new_path.exists():
        print(f"not found: {new_path}\nPut round3.jsonl in the eval folder first.")
        sys.exit(1)

    existing = read_jsonl(data_path)
    new_items = read_jsonl(new_path)
    problems = validate(new_items, {it["id"] for _, it in existing})

    if problems:
        print("NOT appended. Problems found:")
        for p in problems:
            print(" -", p)
        sys.exit(1)

    both = [it for _, it in existing] + [it for _, it in new_items]
    print(f"new items: {len(new_items)}  (dataset will have {len(both)})")
    print("by split:   ", dict(Counter(i.get("split", "dev") for i in both)))
    print("by category:", dict(Counter(i["category"] for i in both)))

    if args.dry_run:
        print("dry run: nothing written")
        return

    backup = data_path.with_suffix(".jsonl.bak3")
    shutil.copy(data_path, backup)
    raw = data_path.read_bytes()
    with open(data_path, "ab") as f:
        if raw and not raw.endswith(b"\n"):
            f.write(b"\n")
        for _, it in new_items:
            f.write((json.dumps(it, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"appended. backup saved to {backup.name}")


if __name__ == "__main__":
    main()
