import json
import random
import re
import urllib.request
from pathlib import Path

URL = ("https://raw.githubusercontent.com/openai/grade-school-math/"
       "master/grade_school_math/data/test.jsonl")
N = 30          # how many items to import
SEED = 42       # fixed seed so the sample is reproducible
DATASET = Path(__file__).resolve().parent / "dataset.jsonl"

with urllib.request.urlopen(URL, timeout=60) as resp:
    rows = [json.loads(line) for line in resp.read().decode("utf-8").splitlines() if line.strip()]

existing = set()
with open(DATASET, encoding="utf-8-sig") as f:
    for line in f:
        if line.strip():
            existing.add(json.loads(line)["id"])

random.Random(SEED).shuffle(rows)
added = 0
with open(DATASET, "a", encoding="utf-8") as f:
    for idx, row in enumerate(rows):
        if added >= N:
            break
        item_id = f"gsm{idx}"
        if item_id in existing:
            continue
        final = row["answer"].split("####")[-1].strip().replace(",", "")
        if not re.fullmatch(r"-?\d+(\.\d+)?", final):
            continue
        value = float(final)
        value = int(value) if value == int(value) else value
        split = "dev" if added < int(N * 0.7) else "test"
        item = {
            "id": item_id,
            "category": "math",
            "split": split,
            "prompt": row["question"] + " End your reply with the final number.",
            "check": {"type": "number", "value": value},
        }
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
        added += 1

print(f"added {added} items to {DATASET}")