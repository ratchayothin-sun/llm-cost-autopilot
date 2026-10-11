import sqlite3

from eval.run_eval import DB_PATH

conn = sqlite3.connect(DB_PATH)
cur = conn.execute(
    "UPDATE results SET error = NULL, output = '[ABORTED: token repeat limit]', "
    "correct = 0 WHERE error LIKE '%token repeat limit%'"
)
conn.commit()
print("updated:", cur.rowcount)