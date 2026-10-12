import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

from app.providers.client import call_model
from app.router.cascade import TIERS

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "dataset.jsonl"
DB_PATH = ROOT / "eval_results.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    item_id TEXT, tier TEXT, category TEXT, model TEXT,
    output TEXT, correct INTEGER, cost REAL, latency REAL, error TEXT,
    PRIMARY KEY (item_id, tier)
);
"""


def load_items():
    items = []
    with open(DATASET, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


# Models such as gpt-oss write typographic characters (non-breaking hyphen U+2011,
# no-break spaces). Treat them as the plain ones before an answer is checked.
_NORMALIZE = {ord(c): "-" for c in "\u2010\u2011\u2212"}
_NORMALIZE.update({ord(c): " " for c in "\u00a0\u202f\u2009"})


def check_answer(output: str, spec: dict) -> bool:
    kind = spec["type"]
    text = (output or "").translate(_NORMALIZE)

    if kind == "contains_any":
        low = text.lower()
        return any(v.lower() in low for v in spec["values"])

    if kind == "number":
        # prefer an explicit "ANSWER: <number>" line; fall back to the last number
        tagged = re.findall(
            r"ANSWER:\s*\$?\s*(-?\d[\d,]*\.?\d*)", text, flags=re.IGNORECASE
        )
        nums = tagged or re.findall(r"-?\d[\d,]*\.?\d*", text)
        if not nums:
            return False
        try:
            last = float(nums[-1].replace(",", "").rstrip("."))
        except ValueError:
            return False
        return abs(last - float(spec["value"])) < 1e-6

    if kind == "json_keys":
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return False
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return False
        if not all(k in data for k in spec["keys"]):
            return False
        for k, v in spec.get("expect", {}).items():
            if str(v).lower() not in str(data.get(k)).lower():
                return False
        return True

    if kind == "regex":
        return re.fullmatch(spec["pattern"], text.strip()) is not None

    raise ValueError(f"unknown check type: {kind}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiers", help="comma-separated tier names")
    parser.add_argument("--limit", type=int, help="only first N items")
    parser.add_argument("--rerun", action="store_true",
                        help="ignore saved results for the selected tiers")
    parser.add_argument("--retry-errors", action="store_true",
                        help="delete failed rows of the selected tiers and run them again")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="seconds to wait after each cloud (non-ollama) call")
    parser.add_argument("--split", default="dev", choices=["dev", "test", "all"],
                        help="which part of the dataset to run (default: dev)")
    parser.add_argument("--max-calls", type=int, default=0,
                        help="max calls per cloud (non-ollama) tier in this run; 0 = no limit")
    args = parser.parse_args()

    tiers = TIERS
    if args.tiers:
        wanted = set(args.tiers.split(","))
        tiers = [t for t in TIERS if t["name"] in wanted]

    items = load_items()
    if args.split != "all":
        items = [i for i in items if i.get("split", "dev") == args.split]
    items = items[: args.limit]

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    if args.retry_errors:
        for tier in tiers:
            conn.execute(
                "DELETE FROM results WHERE error IS NOT NULL AND tier = ?",
                (tier["name"],),
            )
        conn.commit()

    for tier in tiers:
        is_cloud = not tier["model"].startswith("ollama/")
        calls = 0
        for item in items:
            if not args.rerun:
                done = conn.execute(
                    "SELECT 1 FROM results WHERE item_id=? AND tier=?",
                    (item["id"], tier["name"]),
                ).fetchone()
                if done:
                    continue

            if is_cloud and args.max_calls and calls >= args.max_calls:
                print(f"[{tier['name']}] reached --max-calls {args.max_calls}; "
                      f"stopping. Run again later to continue.")
                break

            messages = [{"role": "user", "content": item["prompt"]}]
            out, cost, latency, err, full_err = "", 0.0, 0.0, None, ""
            try:
                r = call_model(tier["model"], messages, tier)
                out, cost, latency = r["text"], r["cost"], r["latency"]
            except Exception as e:
                full_err = str(e)
                err = full_err[:300]
            if is_cloud:
                calls += 1

            # model got stuck in a repetition loop: a model failure, not an
            # infrastructure error, so it counts as a wrong answer
            if err and "token repeat limit" in full_err:
                err = None
                out = "[ABORTED: token repeat limit]"

            # daily quota exhausted: stop this tier and do not save an error row
            if err and any(s in full_err for s in ("PerDay", "(TPD)", "(RPD)", "per day")):
                print(f"[{tier['name']}] daily quota exhausted; stopping this tier. "
                      f"Run again after the quota resets.")
                break

            correct = int(err is None and check_answer(out, item["check"]))
            conn.execute(
                "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?)",
                (item["id"], tier["name"], item["category"], tier["model"],
                 out, correct, cost, latency, err),
            )
            conn.commit()
            status = "ERROR" if err else ("OK" if correct else "WRONG")
            print(f"[{tier['name']}] {item['id']}: {status} ({latency:.1f}s)")

            if args.sleep and is_cloud:
                time.sleep(args.sleep)

    summarize(conn)


def summarize(conn):
    print("\n=== Accuracy by tier x category (errors excluded) ===")
    rows = conn.execute(
        """SELECT tier, category, COUNT(*), SUM(correct)
           FROM results WHERE error IS NULL
           GROUP BY tier, category ORDER BY tier, category"""
    ).fetchall()
    for tier, cat, n, ok in rows:
        print(f"{tier:8} {cat:12} {ok}/{n}  ({100 * ok / n:.0f}%)")

    print("\n=== Overall by tier (errors excluded) ===")
    rows = conn.execute(
        """SELECT tier, COUNT(*), SUM(correct), AVG(cost), AVG(latency)
           FROM results WHERE error IS NULL GROUP BY tier"""
    ).fetchall()
    for tier, n, ok, cost, lat in rows:
        print(f"{tier:8} acc={100 * ok / n:.0f}%  avg_cost={cost:.6f}  "
              f"avg_latency={lat:.1f}s  (n={n})")

    print("\n=== Errors (not counted above) ===")
    rows = conn.execute(
        "SELECT tier, COUNT(*) FROM results WHERE error IS NOT NULL GROUP BY tier"
    ).fetchall()
    print(rows if rows else "none")


if __name__ == "__main__":
    main()