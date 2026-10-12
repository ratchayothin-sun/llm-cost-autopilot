"""Look at WHY items were marked WRONG. Makes no model calls, changes nothing.

For every wrong result it prints the expected answer and the end of the model's
actual output, and flags the likely reason:

  NEAR-MISS      the right answer is in the output but the checker rejected it
                 (not on the ANSWER line, extra words after it, spacing ...)
                 -> possible checker false negative
  NO-ANSWER-LINE the prompt asked for a final "ANSWER: ..." line and the model
                 did not write one -> the model ignored the format
  WRONG-CONTENT  format looked fine, the content is simply wrong -> real failure

Usage (from the project root):
    python -m eval.diagnose --from-file eval/round3.jsonl     # only the new items
    python -m eval.diagnose                                   # every wrong dev item
    python -m eval.diagnose --ids r7 r8 k9 --tiers small

Everything is also written to eval/diagnose_out.txt (UTF-8), so you can attach
that file instead of copying from the terminal.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEAD = r"(?si).*ANSWER:\s*[*_`\s]*"
TAIL = r"[*_`\s.!]*"


def load_dataset(path, split):
    items = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                it = json.loads(line)
                if split == "all" or it.get("split", "dev") == split:
                    items[it["id"]] = it
    return items


def ids_from_file(path):
    with open(path, encoding="utf-8-sig") as f:
        return [json.loads(l)["id"] for l in f if l.strip()]


def describe_expected(spec):
    kind = spec["type"]
    if kind == "number":
        return f"number {spec['value']}"
    if kind == "contains_any":
        return "contains any of: " + " | ".join(spec["values"])
    if kind == "json_keys":
        return f"json keys {spec['keys']} expect {spec.get('expect', {})}"
    pat = spec["pattern"].replace(LEAD, "ANSWER: ").replace(TAIL, "")
    return f"regex {pat}"


def needs_answer_line(item):
    spec = item["check"]
    if spec["type"] == "regex" and "ANSWER" in spec["pattern"]:
        return True
    return spec["type"] == "number" and "ANSWER:" in item["prompt"]


def classify(item, text):
    spec = item["check"]
    kind = spec["type"]
    text = text or ""
    near = []
    if kind == "number":
        flat = text.replace(",", "")
        v = spec["value"]
        s = str(int(v)) if float(v).is_integer() else str(v)
        if re.search(rf"(?<![\d.]){re.escape(s)}(?![\d])", flat):
            near.append("expected number appears, but not as the final/ANSWER number")
    elif kind == "regex":
        pat = spec["pattern"]
        try:
            if re.search(pat, text):
                near.append("answer present but not as the whole reply (extra text around it)")
            elif re.fullmatch(pat, re.sub(r"\s+", "", text)):
                near.append("matches once whitespace is removed (spacing)")
        except re.error:
            pass
    if near:
        return "NEAR-MISS", near[0]
    if needs_answer_line(item) and "answer:" not in text.lower():
        return "NO-ANSWER-LINE", "no 'ANSWER:' in the output"
    return "WRONG-CONTENT", ""


def shorten(text, head=90, tail=170):
    t = (text or "").replace("\r", "").replace("\n", " ⏎ ")
    if len(t) <= head + tail + 10:
        return t
    return t[:head] + " … " + t[-tail:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "eval_results.db"))
    ap.add_argument("--dataset", default=str(ROOT / "dataset.jsonl"))
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--tiers", nargs="+", default=["small", "medium"])
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--from-file", help="a .jsonl whose ids to look at, e.g. eval/round3.jsonl")
    ap.add_argument("--out", default=str(ROOT / "diagnose_out.txt"))
    args = ap.parse_args()

    items = load_dataset(args.dataset, args.split)
    wanted = None
    if args.ids:
        wanted = set(args.ids)
    if args.from_file:
        wanted = (wanted or set()) | set(ids_from_file(args.from_file))
    if wanted is not None:
        items = {k: v for k, v in items.items() if k in wanted}

    conn = sqlite3.connect(args.db)
    res = {}
    for item_id, tier, output, correct in conn.execute(
        "SELECT item_id, tier, output, correct FROM results WHERE error IS NULL"
    ):
        if item_id in items and tier in args.tiers:
            res.setdefault(item_id, {})[tier] = (output, int(correct))

    lines = []
    counts = {t: {"NEAR-MISS": 0, "NO-ANSWER-LINE": 0, "WRONG-CONTENT": 0, "ok": 0, "n": 0}
              for t in args.tiers}
    shown = 0
    for item_id in sorted(items):
        r = res.get(item_id, {})
        for t in args.tiers:
            if t in r:
                counts[t]["n"] += 1
                if r[t][1]:
                    counts[t]["ok"] += 1
        wrong_tiers = [t for t in args.tiers if t in r and not r[t][1]]
        if not wrong_tiers:
            continue
        item = items[item_id]
        shown += 1
        lines.append(f"== {item_id} ({item.get('category', '?')})  expected: {describe_expected(item['check'])}")
        for t in args.tiers:
            if t not in r:
                lines.append(f"   {t:7} (not run)")
                continue
            out, ok = r[t]
            if ok:
                lines.append(f"   {t:7} ok")
                continue
            label, why = classify(item, out)
            counts[t][label] += 1
            extra = f" ({why})" if why else ""
            lines.append(f"   {t:7} {label}{extra}  len={len(out or '')}")
            lines.append(f"           {shorten(out)}")
        lines.append("")

    lines.append("=== Summary of WRONG results by likely reason ===")
    for t in args.tiers:
        c = counts[t]
        wrong = c["NEAR-MISS"] + c["NO-ANSWER-LINE"] + c["WRONG-CONTENT"]
        lines.append(f"{t:7} ran {c['n']:3}  ok {c['ok']:3}  wrong {wrong:3} = "
                     f"near-miss {c['NEAR-MISS']}, no-answer-line {c['NO-ANSWER-LINE']}, "
                     f"wrong-content {c['WRONG-CONTENT']}")
    lines.append("")
    lines.append("How to read this:")
    lines.append(" - near-miss: look at these first; if the answer is really right, the checker is too strict.")
    lines.append(" - no-answer-line: the model ignored the format. A real weakness of the model, but a")
    lines.append("   different one from 'does not know the answer'; report them separately.")
    lines.append(" - wrong-content: genuine failures. These are the ones a bigger model should rescue.")
    lines.append(" - Any checker change made after reading this is a dev-set change: write it down for the README.")

    text = "\n".join(lines)
    if not shown:
        text = "No wrong results found for the selected items/tiers.\n\n" + text
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode())
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"\n(also saved to {args.out})")


if __name__ == "__main__":
    sys.exit(main())