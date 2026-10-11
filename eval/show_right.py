import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / "eval_results.db"
conn = sqlite3.connect(DB)
tier = sys.argv[1] if len(sys.argv) > 1 else "small"

for item_id, output in conn.execute(
    "SELECT item_id, output FROM results "
    "WHERE correct = 1 AND error IS NULL AND tier = ? ORDER BY item_id",
    (tier,),
):
    print(f"--- [{tier}] {item_id} ---")
    print((output or "")[:300])
    print()