"""One-time fixes found with eval.diagnose. Run from the project root:

    python -m eval.apply_fixes --dry-run     # show what would change, write nothing
    python -m eval.apply_fixes               # apply

1. eval/run_eval.py: normalise typographic characters in the model output before it is
   checked. gpt-oss writes "hot-headed" with a NON-BREAKING hyphen (U+2011), which never
   matched the expected "hot-headed". Only hyphen/minus look-alikes and no-break spaces
   are mapped; no answer becomes easier to get right.
2. eval/dataset.jsonl: the Thai instruction "ตอบท้ายด้วยตัวเลขสุดท้าย" is ambiguous.
   Models read it as "the last DIGIT" and answered e.g. "225, 5". It is replaced by the
   explicit "ANSWER: <number>" line the newer items already use, and the stored results
   of those items are deleted so that eval.run_eval runs them again.

Both are changes made after looking at dev results: mention them in the README.
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN_EVAL = ROOT / "run_eval.py"
DATASET = ROOT / "dataset.jsonl"
DB = ROOT / "eval_results.db"

OLD_PHRASE = re.compile(r"ตอบท้ายด้วยตัวเลขสุดท้าย\.?")
NEW_PHRASE = ("ลงท้ายคำตอบด้วยบรรทัดสุดท้ายในรูปแบบ ANSWER: <ตัวเลข> "
              "(เฉพาะตัวเลข ไม่มีหน่วย ไม่มีเครื่องหมายจุลภาค)")

CONST = '''# Models such as gpt-oss write typographic characters (non-breaking hyphen U+2011,
# no-break spaces). Treat them as the plain ones before an answer is checked.
_NORMALIZE = {ord(c): "-" for c in "\\u2010\\u2011\\u2212"}
_NORMALIZE.update({ord(c): " " for c in "\\u00a0\\u202f\\u2009"})


'''
DEF_LINE = "def check_answer(output: str, spec: dict) -> bool:\n"
TEXT_OLD = '    text = output or ""\n'
TEXT_NEW = '    text = (output or "").translate(_NORMALIZE)\n'


def read_text_keep(path):
    """Return (text with \\n newlines, had_bom, used_crlf)."""
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    crlf = "\r\n" in text
    return text.replace("\r\n", "\n"), bom, crlf


def write_text_keep(path, text, bom, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)


def patch_run_eval(dry):
    if not RUN_EVAL.exists():
        return f"run_eval.py not found at {RUN_EVAL}", False
    text, bom, crlf = read_text_keep(RUN_EVAL)
    if "_NORMALIZE" in text:
        return "run_eval.py: already patched, nothing to do", False
    problems = []
    if text.count(DEF_LINE) != 1:
        problems.append(f"expected exactly one {DEF_LINE.strip()!r}, found {text.count(DEF_LINE)}")
    if text.count(TEXT_OLD) != 1:
        problems.append(f"expected exactly one {TEXT_OLD.strip()!r}, found {text.count(TEXT_OLD)}")
    if problems:
        return "run_eval.py NOT patched (the file differs from what this script expects): " + "; ".join(problems), None
    new = text.replace(DEF_LINE, CONST + DEF_LINE).replace(TEXT_OLD, TEXT_NEW)
    try:
        compile(new, str(RUN_EVAL), "exec")
    except SyntaxError as e:
        return f"run_eval.py NOT patched (result would not compile: {e})", None
    if dry:
        return "run_eval.py: would add _NORMALIZE and use it in check_answer", True
    shutil.copy(RUN_EVAL, RUN_EVAL.with_suffix(".py.bak"))
    write_text_keep(RUN_EVAL, new, bom, crlf)
    return "run_eval.py: patched (backup run_eval.py.bak)", True


def fix_dataset(dry):
    if not DATASET.exists():
        return f"dataset not found at {DATASET}", [], False
    raw = DATASET.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").splitlines(keepends=True)
    changed, out = [], []
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        it = json.loads(line)
        if OLD_PHRASE.search(it.get("prompt", "")):
            if it.get("check", {}).get("type") != "number":
                print(f"warning: {it['id']} has the phrase but is not a number check; left alone")
                out.append(line)
                continue
            it["prompt"] = OLD_PHRASE.sub(NEW_PHRASE, it["prompt"])
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            out.append(json.dumps(it, ensure_ascii=False) + ending)
            changed.append(it["id"])
        else:
            out.append(line)
    if not changed:
        return "dataset.jsonl: no prompt contains the ambiguous phrase, nothing to do", [], False
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    if dry:
        return f"dataset.jsonl: would rewrite the prompt of {', '.join(changed)}", changed, True
    shutil.copy(DATASET, DATASET.with_suffix(".jsonl.bak4"))
    DATASET.write_bytes((b"\xef\xbb\xbf" if bom else b"") + "".join(out).encode("utf-8"))
    return f"dataset.jsonl: rewrote the prompt of {', '.join(changed)} (backup dataset.jsonl.bak4)", changed, True


def drop_results(ids, dry):
    if not ids or not DB.exists():
        return "results: nothing to delete"
    conn = sqlite3.connect(DB)
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT tier, COUNT(*) FROM results WHERE item_id IN ({marks}) GROUP BY tier", ids
    ).fetchall()
    n = sum(c for _, c in rows)
    detail = ", ".join(f"{t}: {c}" for t, c in rows) or "none"
    if dry:
        conn.close()
        return f"results: would delete {n} stored rows of those items ({detail})"
    conn.close()
    backup = DB.with_name("eval_results_pre_apply_fixes.db")
    shutil.copy(DB, backup)
    conn = sqlite3.connect(DB)
    conn.execute(f"DELETE FROM results WHERE item_id IN ({marks})", ids)
    conn.commit()
    conn.close()
    return f"results: deleted {n} stored rows ({detail}); database backup {backup.name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    msg1, patched = patch_run_eval(args.dry_run)
    print(msg1)
    if patched is None:
        sys.exit(1)
    msg2, ids, _ = fix_dataset(args.dry_run)
    print(msg2)
    print(drop_results(ids, args.dry_run))
    if args.dry_run:
        print("dry run: nothing written")
    else:
        print("\nNext: python -m eval.rescore --dry-run  (then without --dry-run),\n"
              "      then run_eval for small, medium and large to fill in the deleted rows.")


if __name__ == "__main__":
    main()
