import sqlite3

from eval.run_eval import DB_PATH, check_answer, load_items

items = {i["id"]: i for i in load_items()}
conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT item_id, tier, output, correct FROM results WHERE error IS NULL"
).fetchall()

changed = 0
for item_id, tier, output, old in rows:
    new = int(check_answer(output, items[item_id]["check"]))
    if new != old:
        print(f"{tier} {item_id}: {old} -> {new}")
        conn.execute(
            "UPDATE results SET correct=? WHERE item_id=? AND tier=?",
            (new, item_id, tier),
        )
        changed += 1
conn.commit()
print("changed:", changed)