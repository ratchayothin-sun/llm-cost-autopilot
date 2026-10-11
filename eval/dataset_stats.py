import json
from collections import Counter
from pathlib import Path

DATASET = Path(__file__).resolve().parent / "dataset.jsonl"
VALID_CHECKS = {"number", "contains_any", "json_keys", "regex"}

items, problems, seen = [], [], set()
with open(DATASET, encoding="utf-8-sig") as f:
    for n, line in enumerate(f, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"line {n}: invalid JSON ({e})")
            continue
        for key in ("id", "category", "prompt", "check"):
            if key not in item:
                problems.append(f"line {n}: missing '{key}'")
        if item.get("id") in seen:
            problems.append(f"line {n}: duplicate id {item.get('id')}")
        seen.add(item.get("id"))
        if item.get("check", {}).get("type") not in VALID_CHECKS:
            problems.append(f"line {n}: unknown check type in {item.get('id')}")
        items.append(item)

print(f"total items: {len(items)}\n")
print("by split:   ", dict(Counter(i.get("split", "dev") for i in items)))
print("by category:", dict(Counter(i["category"] for i in items if "category" in i)))
print()
for cat, n in sorted(Counter((i.get("category"), i.get("split", "dev")) for i in items).items(), key=str):
    print(f"  {cat}: {n}")

print("\nproblems:", "none" if not problems else "")
for p in problems:
    print(" -", p)