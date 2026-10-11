import sqlite3

from eval.run_eval import DB_PATH

conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT item_id, tier, correct, cost FROM results WHERE error IS NULL"
).fetchall()

data = {}
for item_id, tier, correct, cost in rows:
    data.setdefault(item_id, {})[tier] = (correct, cost)

ids = [i for i, t in data.items() if "small" in t and "large" in t]
n = len(ids)


def report(name, correct_total, cost_total):
    print(f"{name:34} acc={100 * correct_total / n:5.1f}%  "
          f"avg_cost={cost_total / n:.6f}")


# always-small / always-large
report("always small", sum(data[i]["small"][0] for i in ids),
       sum(data[i]["small"][1] for i in ids))
report("always large", sum(data[i]["large"][0] for i in ids),
       sum(data[i]["large"][1] for i in ids))

# oracle: use small when small is right, otherwise go to large.
# Lower bound on cost assumes a free, perfect verifier.
oc, ocost = 0, 0.0
for i in ids:
    s, l = data[i]["small"], data[i]["large"]
    if s[0]:
        oc += 1
        ocost += s[1]
    else:
        oc += l[0]
        ocost += s[1] + l[1]  # small was still paid for
report("oracle cascade (perfect verifier)", oc, ocost)

print(f"\nn = {n} items")