"""Send a few requests to a running gateway and print what the router did with each.

Terminal 1 (project root, venv active):
    $env:AUTOPILOT_POLICY = "router"
    uvicorn app.main:app

Terminal 2:
    python -m eval.demo_gateway

This is a smoke test of the whole path (HTTP -> policy -> model -> verifier -> SQLite log),
not a benchmark: eight prompts say nothing about accuracy. The cost column is the same
simulated cost used in the evaluation, not money spent.
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

ANSWER_NUM = "ลงท้ายคำตอบด้วยบรรทัดสุดท้ายในรูปแบบ ANSWER: <ตัวเลข> (เฉพาะตัวเลข ไม่มีหน่วย ไม่มีเครื่องหมายจุลภาค)"

# (task_type, prompt, tier the router is expected to use when nothing needs escalating)
REQUESTS = [
    ("knowledge", "วัดอรุณราชวรารามตั้งอยู่ริมแม่น้ำสายใดในกรุงเทพมหานคร ตอบสั้นๆ", "large"),
    ("knowledge", "Who painted the Mona Lisa? Answer briefly.", "large"),
    ("math", "ร้านขายปากกาเป็นโหลๆ ละ 12 ด้าม ด้ามละ 15 บาท ซื้อ 3 โหลต้องจ่ายกี่บาท " + ANSWER_NUM, "medium"),
    ("math", "A train travels 150 km in 2.5 hours. What is its average speed in km/h? End your reply with the final number.", "medium"),
    ("reasoning", "วันนี้เป็นวันพุธ อีก 20 วันข้างหน้าจะเป็นวันอะไรของสัปดาห์ ลงท้ายคำตอบด้วยบรรทัดสุดท้ายในรูปแบบ ANSWER: <คำตอบ> (ใส่เฉพาะชื่อวัน)", "medium"),
    ("extraction", "Extract JSON with keys name, city from: 'Mali lives in Phuket.' Return only the JSON.", "small"),
    (None, "สรุปข้อดีของการออมเงินเป็นประจำเป็น 2 ประโยค", "medium"),
    (None, "What is the capital of Canada? Answer briefly.", "medium"),
]


def run_demo(client, base_url, requests=REQUESTS):
    """POST each request to the gateway; return one result row per request."""
    rows = []
    for task_type, prompt, expected in requests:
        started = time.perf_counter()
        resp = client.post(
            f"{base_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": prompt}], "task_type": task_type},
        )
        wall = time.perf_counter() - started
        resp.raise_for_status()
        data = resp.json()
        rows.append({
            "task_type": task_type or "-",
            "expected": expected,
            "tier": data.get("tier_used", "?"),
            "escalations": data.get("escalations", 0),
            "cost": float(data.get("total_cost", 0.0)),
            "policy": data.get("policy", "?"),
            "seconds": wall,
            "text": (data.get("text") or "").strip().replace("\n", " "),
        })
    return rows


def policy_warning(rows):
    """A message when the gateway is not running the router policy, else None."""
    policies = {r["policy"] for r in rows}
    if policies == {"router"}:
        return None
    return (f"gateway reported policy {sorted(policies)}, not 'router'. Stop it and restart with "
            "$env:AUTOPILOT_POLICY = \"router\" in the same terminal before running uvicorn.")


def format_table(rows):
    lines = [f"{'task_type':11s} {'tier used':9s} {'esc':>3s} {'cost':>10s} {'secs':>6s}  answer"]
    for r in rows:
        # an escalated request legitimately ends in a different tier than it started in
        unexpected = r["escalations"] == 0 and r["tier"] != r["expected"]
        mark = f"  (expected {r['expected']})" if unexpected else ""
        lines.append(f"{r['task_type']:11s} {r['tier']:9s} {r['escalations']:3d} {r['cost']:10.6f} "
                     f"{r['seconds']:6.1f}  {r['text'][:60]}{mark}")
    total = sum(r["cost"] for r in rows)
    lines.append(f"{'total':11s} {'':9s} {sum(r['escalations'] for r in rows):3d} {total:10.6f}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # keep going if the console cannot show Thai

    try:
        with httpx.Client(timeout=300) as client:   # the local small tier can take 30+ s on a CPU
            rows = run_demo(client, args.url)
    except httpx.ConnectError:
        print(f"cannot reach the gateway at {args.url}. Start it first: uvicorn app.main:app")
        return 1
    except httpx.HTTPStatusError as e:
        print(f"gateway returned {e.response.status_code}: {e.response.text[:300]}")
        return 1

    print(format_table(rows))
    warning = policy_warning(rows)
    if warning:
        print("\nWARNING:", warning)
    print("\nEvery attempt was also written to autopilot.db (tables: requests, attempts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
