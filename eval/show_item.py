import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / "eval_results.db"
conn = sqlite3.connect(DB)
tier = sys.argv[1]
item_id = sys.argv[2]

row = conn.execute(
    "SELECT tier, item_id, correct, error, substr(output, 1, 300) "
    "FROM results WHERE tier = ? AND item_id = ?",
    (tier, item_id),
).fetchone()
print(row if row else "no such row")