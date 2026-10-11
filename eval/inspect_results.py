import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / "eval_results.db"
conn = sqlite3.connect(DB)

mode = sys.argv[1] if len(sys.argv) > 1 else "wrong"
arg = sys.argv[2] if len(sys.argv) > 2 else None

if mode == "wrong":
    # answers judged incorrect (errors excluded); optional tier filter
    query = (
        "SELECT tier, item_id, output FROM results "
        "WHERE correct = 0 AND error IS NULL"
    )
    params = ()
    if arg:
        query += " AND tier = ?"
        params = (arg,)
    query += " ORDER BY tier, item_id"
    for tier, item_id, output in conn.execute(query, params).fetchall():
        print(f"--- [{tier}] {item_id} ---")
        print((output or "")[:400])
        print()

elif mode == "errors":
    # distinct error messages per tier, with counts
    for tier, err, n in conn.execute(
        "SELECT tier, substr(error, 1, 300), COUNT(*) FROM results "
        "WHERE error IS NOT NULL GROUP BY tier, substr(error, 1, 300)"
    ):
        print(f"[{tier}] x{n}: {err}\n")

elif mode == "models":
    # which model produced the results of each tier
    for row in conn.execute(
        "SELECT tier, model, COUNT(*) FROM results GROUP BY tier, model"
    ):
        print(row)

else:
    print("usage: python eval\\inspect_results.py [wrong [tier] | errors | models]")