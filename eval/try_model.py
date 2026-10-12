"""Smoke-test ONE model through LiteLLM on a few eval items. Writes nothing to the eval DB.

Usage (from the project root):
    python -m eval.try_model --model groq/openai/gpt-oss-120b
    python -m eval.try_model --model groq/openai/gpt-oss-20b --ids r7 k10 m10
    python -m eval.try_model --model groq/openai/gpt-oss-20b --ids k10 t5 --max-tokens 8192
    python -m eval.try_model --model groq/openai/gpt-oss-20b --reasoning-effort low

The provider key must be in .env (Groq: GROQ_API_KEY=...). Never paste the key in chat.

What to look at in the output:
  - an error line      -> bad key (401), unknown model name (404), or rate limit (429)
  - finish=length and an empty answer -> the model spent its token budget "thinking";
                          raise --max-tokens
  - tokens/call        -> multiply by the number of items to see if one full eval run fits
                          in the provider's daily token limit
"""
import argparse
import json
import time
from pathlib import Path

try:  # LiteLLM normally loads .env itself; this is a harmless second attempt
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

import litellm

ROOT = Path(__file__).resolve().parent
DEFAULT_IDS = ["r7", "r8", "r10", "k10", "k13", "k15", "m10", "m12", "t5", "t7"]


def load_items(path, wanted):
    items = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                it = json.loads(line)
                items[it["id"]] = it
    missing = [i for i in wanted if i not in items]
    if missing:
        print("ids not in dataset (skipped):", ", ".join(missing))
    return [items[i] for i in wanted if i in items]


def get(obj, *names, default=None):
    for n in names:
        obj = getattr(obj, n, None)
        if obj is None:
            return default
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="LiteLLM model string, e.g. groq/openai/gpt-oss-120b")
    ap.add_argument("--ids", nargs="+", default=DEFAULT_IDS)
    ap.add_argument("--dataset", default=str(ROOT / "dataset.jsonl"))
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--sleep", type=float, default=4.0, help="seconds between calls (tokens-per-minute limits)")
    ap.add_argument("--reasoning-effort", choices=["low", "medium", "high"],
                    help="for reasoning models (gpt-oss): how long the model may think before answering")
    args = ap.parse_args()

    try:
        from eval.run_eval import check_answer
    except Exception as e:  # checker is optional here
        check_answer = None
        print(f"(checker not available, only showing answers: {type(e).__name__}: {e})")

    extra = {}
    if args.reasoning_effort:
        extra["reasoning_effort"] = args.reasoning_effort

    items = load_items(args.dataset, args.ids)
    ok = n = 0
    total_tokens = 0
    total_latency = 0.0
    for idx, it in enumerate(items):
        if idx:
            time.sleep(args.sleep)
        t0 = time.time()
        try:
            resp = litellm.completion(
                model=args.model,
                messages=[{"role": "user", "content": it["prompt"]}],
                temperature=0,
                max_tokens=args.max_tokens,
                timeout=120,
                **extra,
            )
        except Exception as e:
            print(f"[{it['id']}] ERROR {type(e).__name__}: {str(e)[:300]}")
            if "PerDay" in str(e) or "per day" in str(e).lower():
                print("daily quota reached - stopping")
                break
            continue
        dt = time.time() - t0
        text = get(resp, "choices") and (resp.choices[0].message.content or "") or ""
        finish = get(resp, "choices") and resp.choices[0].finish_reason
        pt = get(resp, "usage", "prompt_tokens", default=0) or 0
        ct = get(resp, "usage", "completion_tokens", default=0) or 0
        rt = get(resp, "usage", "completion_tokens_details", "reasoning_tokens", default=0) or 0
        total_tokens += pt + ct
        total_latency += dt
        n += 1
        verdict = ""
        if check_answer is not None:
            good = check_answer(text, it["check"])
            ok += int(good)
            verdict = "OK   " if good else "WRONG"
        shown = text.strip().replace("\n", " ⏎ ")
        shown = shown if len(shown) <= 220 else "… " + shown[-220:]
        print(f"[{it['id']}] {verdict} {dt:4.1f}s finish={finish} tokens in/out={pt}/{ct}"
              f"{f' (reasoning {rt})' if rt else ''}")
        print(f"      {shown or '(EMPTY ANSWER)'}")

    print()
    if n:
        print(f"{n} calls succeeded" + (f", {ok} correct by the checker" if check_answer else ""))
        print(f"average {total_tokens / n:.0f} tokens/call, {total_latency / n:.1f}s/call")
        print(f"a full 101-item run would use about {101 * total_tokens / n:,.0f} tokens "
              f"(compare with the provider's daily token limit)")
    else:
        print("no successful calls")


if __name__ == "__main__":
    main()