import re
import sqlite3
import sys

from eval.run_eval import DB_PATH, load_items

tier_filter = sys.argv[1] if len(sys.argv) > 1 else None
items = {i["id"]: i for i in load_items()}
conn = sqlite3.connect(DB_PATH)

query = (
    "SELECT tier, item_id, output FROM results "
    "WHERE correct = 0 AND error IS NULL AND category = 'math'"
)
params = ()
if tier_filter:
    query += " AND tier = ?"
    params = (tier_filter,)
query += " ORDER BY item_id, tier"

for tier, item_id, output in conn.execute(query, params).fetchall():
    item = items.get(item_id)
    expected = item["check"].get("value") if item else None
    nums = re.findall(r"-?\d[\d,]*\.?\d*", output or "")
    extracted = nums[-1] if nums else None
    print(f"--- [{tier}] {item_id}  expected={expected}  extracted={extracted} ---")
    print("PROMPT:", item["prompt"][:300] if item else "?")
    print("TAIL:  ", (output or "")[-250:].replace("\n", " "))
    print()