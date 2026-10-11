import json
import shutil
import sqlite3
from pathlib import Path

from eval.run_eval import DATASET, DB_PATH

OLD = "End your reply with the final number."
NEW = ("End your reply with a final line in exactly this form: "
       "ANSWER: <number> (digits only, no units).")

shutil.copy(DATASET, DATASET.with_suffix(".jsonl.bak2"))

lines, changed = [], 0
with open(DATASET, encoding="utf-8-sig") as f:
    for line in f:
        if not line.strip():
            continue
        item = json.loads(line)
        if item["id"].startswith("gsm") and OLD in item["prompt"]:
            item["prompt"] = item["prompt"].replace(OLD, NEW)
            changed += 1
        lines.append(json.dumps(item, ensure_ascii=False))

with open(DATASET, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

conn = sqlite3.connect(DB_PATH)
cur = conn.execute("DELETE FROM results WHERE item_id LIKE 'gsm%'")
conn.commit()
print(f"prompts updated: {changed}; result rows deleted: {cur.rowcount}")