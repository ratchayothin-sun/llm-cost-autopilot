# LLM Cost Autopilot

![tests](https://github.com/ratchayothin-sun/llm-cost-autopilot/actions/workflows/tests.yml/badge.svg)

Routes every request to the cheapest model that can handle it, then verifies the call was right.

> **Status:** all four phases are done: gateway and cascade, a rule-based router, format checks as
> verifiers, and an offline benchmark. **Result in one line:** on 58 held-out items the router reached
> 91.4% accuracy at 46% of the always-large cost (always-medium: 81.0% at 30%). Costs are simulated and
> the test set is small and knowledge-heavy; see Results for what worked and what did not.

## Problem

Calling the largest LLM for every request is expensive, but most requests
don't need it. This project puts a gateway in front of multiple models that
tries cheaper models first and escalates only when the answer fails a check.

## Architecture

```
Client -> FastAPI gateway -> Cascade (tier 1 -> tier 2 -> ...) -> Verifier
                                   |                                  |
                                   +----------> SQLite log <----------+
```

- **Gateway:** FastAPI, `POST /v1/chat/completions` (body: `messages` and an optional `task_type`)
- **Providers:** LiteLLM; small tier on local Ollama (Llama 3.2), medium and large on the Groq free tier
- **Router:** a policy (`app/router/policy.py`) picks which tiers to try, and in which order, from `task_type`
- **Cascade:** tries the planned tiers in order and escalates on an error or a rejected answer;
  the last tier's answer is returned even if it fails the check
- **Verifiers:** `app/router/verifiers.py`: non-empty check and format rules (required `ANSWER:` line,
  valid JSON, no stray CJK characters)
- **Logging:** every request and every attempt (tokens, simulated cost, latency, verdict) in SQLite
- **Tests:** pytest with mocked model calls, run by GitHub Actions on every push to `main` and on pull requests
- **Benchmark:** `eval/` holds the dataset, the stored answers of every tier and an offline replay of routing policies

## Cost model

Prices in `configs/models.yaml` are *reference prices* of comparable paid
models, used to compute **simulated cost** for comparing strategies.
No money is actually spent: the models run locally or on free tiers.
Reported savings are relative (e.g. "-X% simulated cost"), not real currency.

## Results

**In one paragraph.** On a held-out test set of 58 items, a rule-based router that sends
general-knowledge questions straight to the large model and everything else to the medium
model reached 91.4% accuracy at about 46% of the always-large cost. Always-medium reached
81.0% at 30%; always-large reached 93.1% at 100%. The router fixed 6 of the medium model's
11 errors and broke none (exact sign test p = 0.03). The test set was written after the
dev analysis and is knowledge-heavy, so read this as a test of one hypothesis, not as overall
accuracy. Cheap verifiers did **not** help: see "What did not work".

### Setup

| Tier | Model | Where it runs |
|---|---|---|
| small | Llama 3.2 (Ollama `latest`) | local, CPU |
| medium | `openai/gpt-oss-20b` | Groq free tier |
| large | `openai/gpt-oss-120b` | Groq free tier |

- **Costs are simulated, not money spent.** They are computed from token counts and reference
  prices (Groq list prices checked 2026-10-12; the small tier is priced at an assumed reference
  price even though it runs locally for free). Only ratios are meaningful. Always-large costs
  about 0.00013 per request on this data.
- **Dataset:** 133 items, Thai and English: math 47, knowledge 42, reasoning 18, extraction 17,
  instruction 9. 30 math items are adapted from GSM8K, so training-data contamination is possible.
  Answers are checked automatically (number, keyword, JSON keys, regex).
- **Split and protocol:** 75 dev items, 58 test items. The dev split was used to fix checkers and
  prompts and to choose the routing table, so dev numbers are in-sample. The routing table
  (`app/router/policy.py`) was committed before any test item was run. The test split was
  replayed once; 32 of its 58 items were written after the dev analysis, specifically to probe
  the weakness found in dev (knowledge questions in Thai), so 28 of 58 test items are knowledge.
- **Policies** (`app/router/policy.py`): `cascade` tries small, medium, large and accepts any
  non-empty answer (the Phase 1 behaviour). `cascade_format` adds format checks. `router`
  picks the tiers from `task_type`: knowledge goes to large, extraction goes small, then medium,
  then large, and everything else goes medium, then large, with format checks between tiers.

### Test split (n = 58, run once)

| Policy | Accuracy (95% CI) | Cost vs always-large | Avg latency |
|---|---|---|---|
| always small | 50.0% (38-62) | 7% | 11.7 s |
| cascade, non-empty verifier (= always small) | 50.0% (38-62) | 7% | 11.7 s |
| cascade + format checks | 56.9% (44-69) | 11% | 11.7 s |
| always medium | 81.0% (69-89) | 30% | 0.6 s |
| **router** (true task_type) | **91.4% (81-96)** | **46%** | 1.8 s |
| router (task_type guessed from the prompt text) | 91.4% (81-96) | 45% | 1.6 s |
| always large | 93.1% (84-97) | 100% | 0.9 s |
| small + medium agree, else large | 93.1% (84-97) | 120% | 12.4 s |

Reference ceilings (a perfect verifier or router, not achievable): medium then large 93.1% at 48%;
omniscient router 93.1% at 30%.

- **Router vs always-medium:** +6 / -0 items (exact sign test p = 0.03). This is the one comparison
  fixed in advance; the other rows are exploratory.
- **Router vs always-large:** 53 vs 54 correct items (one item, an extraction case).
- **Latency** is dominated by the small tier running on a CPU (about 12 s per request); the
  router only uses it for extraction.
- **Sensitivity:** two test items are ambiguous by my own wording (see below) and every tier fails
  both. Without them (n = 56): small 51.8%, medium 83.9% (72-91), router 94.6% (85-98),
  large 96.4% (88-99). The conclusions do not change.

### Dev split (n = 75, in-sample)

| Policy | Accuracy (95% CI) | Cost vs always-large |
|---|---|---|
| always small (= Phase 1 cascade) | 62.7% (51-73) | 8% |
| always medium | 92.0% (84-96) | 25% |
| router | 97.3% (91-99) | 34% |
| always large | 98.7% (93-100) | 100% |

### What did not work

- **Rule-based format checks** (required `ANSWER:` line, valid JSON, no stray CJK characters)
  reject some wrong answers from the small model (4 of its errors on test, 7 on dev) but none
  of the medium model's (0 of 11 on test, 0 of 6 on dev). The medium model's errors are fluent,
  well-formatted, factually wrong answers, which format rules cannot see.
- **Agreement between small and medium** is a poor escalation signal. Free-text answers cannot
  be compared reliably, and when the two disagree it is usually the small model that is wrong, so
  the policy ends up calling all three tiers and costs more than always-large (120% on test).
- **The Phase 1 verifier** (accept any non-empty answer) never escalates, so the default
  cascade behaves exactly like always-small.
- **A learned judge was not tried.** Because the large tier is already cheap on Groq, a judge call
  would eat most of the possible saving; this is untested, not disproven.

### Known issues and limitations

- **Ambiguous items (my wording):** `gsm29` (monthly interest of 2%: simple, gold 106, or compound,
  106.12) and `k34` ("what type of literature is Khun Chang Khun Phaen": the gold answer is
  *sepha*, a verse form, while both models answered "epic", a defensible genre label). Both are
  counted wrong for every tier in the headline numbers.
- **The large model also gets Thai knowledge wrong** (for example it answered Chiang Mai for
  the province nicknamed "city of three mists", Mae Hong Son), so the ceiling here is about 93%.
- **The extraction route has no real verifier for values.** `j11` (an address where `district`
  means *amphoe*, not *tambon*) came back as valid JSON with a wrong value; only the large tier got it right.
- **The test split is not a natural traffic mix.** It is knowledge-heavy (48%) and was written by
  the same author, in the same style, as dev. The router's cost (46% vs 34% on dev) rises with
  the share of knowledge questions it sends to the large tier.
- **The task-type guesser** (character n-gram TF-IDF + logistic regression on the prompt text) got
  52/58 categories right on test and 59/75 on dev (leave-one-out). It may be learning my prompt
  templates (for example a trailing "answer briefly" in Thai) rather than difficulty. It has not been
  tested on prompts written by someone else.
- **Sample size:** n = 58 gives wide intervals. The router's and always-large's intervals overlap
  heavily, so the data cannot separate them.
- **Not an end-to-end gateway benchmark.** Results are replayed from stored answers; the gateway
  itself is covered by unit tests with mocked model calls.

### Reproduce

The stored answers of every tier are in `eval/eval_results.db`, so the replay needs no API keys, no Ollama and no network. Re-running the models themselves (`python -m eval.run_eval`) needs all three.

```powershell
python -m pytest -q                              # unit tests, no API calls
python -m eval.replay                            # dev split, from stored results
python -m eval.replay --split test --auto-classify
```

To use the router in the gateway, set `AUTOPILOT_POLICY=router` and send `task_type`
(`knowledge`, `extraction`, `math`, ...) in the request body. Without it the gateway keeps the
Phase 1 behaviour.

## Quick start

```powershell
git clone https://github.com/ratchayothin-sun/llm-cost-autopilot
cd llm-cost-autopilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q                       # unit tests; every model call is mocked
python -m eval.replay                     # replay the stored benchmark answers, no API keys needed
```

To run the gateway you need a free [Groq](https://console.groq.com) API key and a local
[Ollama](https://ollama.com) with `ollama pull llama3.2`. Keep the key out of git:

```powershell
$env:GROQ_API_KEY = "<your key>"
$env:OLLAMA_API_BASE = "http://127.0.0.1:11434"    # only if localhost does not reach Ollama
$env:AUTOPILOT_POLICY = "router"                   # default is "cascade"
uvicorn app.main:app                               # then open http://127.0.0.1:8000/docs
```

## Gateway demo

A smoke test of the whole path (HTTP request, routing policy, model call, verifier, SQLite log).
Eight prompts say nothing about accuracy; this only shows which tier each request was sent to.

```powershell
$env:AUTOPILOT_POLICY = "router"
uvicorn app.main:app          # terminal 1
python -m eval.demo_gateway   # terminal 2
```

```
task_type   tier used esc       cost   secs  answer
knowledge   large       0   0.000077    1.0  แม่น้ำเจ้าพระยา.
knowledge   large       0   0.000042    0.6  Leonardo da Vinci.
math        medium      0   0.000025    0.6  ANSWER: 540
math        medium      0   0.000016    0.4  60
reasoning   medium      0   0.000035    1.2  ANSWER: Tuesday
extraction  small       0   0.000004   25.3  {"name": "Mali", "city": "Phuket"}
-           medium      0   0.000033    0.7  การออมเงินเป็นประจำช่วยสร้างนิสัยการใช้จ่ายที่มีสติและลดความ
-           medium      0   0.000011    0.3  Ottawa.
total                   0   0.000243
```

- Knowledge questions went straight to the large model, math and reasoning to the medium model,
  and a request without a `task_type` took the default route (medium, then large).
- Costs are simulated from reference prices, not money spent.
- The extraction request ran on the small model locally on a CPU and took 25 s, against about 1 s
  for the hosted tiers. Routing extraction to the small tier saves roughly 0.00001 to 0.00003 of
  simulated cost per request on this data, so it only makes sense where that latency is acceptable or the
  small model is hosted somewhere faster. Medium and small scored the same on the extraction items
  (16 of 17), so this route was chosen for cost, not accuracy.
- Every attempt is stored in `autopilot.db` (tables `requests` and `attempts`), for example:

```powershell
python -c "import sqlite3; c=sqlite3.connect('autopilot.db'); [print(r) for r in c.execute('SELECT id, task_type, final_tier, total_cost, escalations FROM requests ORDER BY id DESC LIMIT 8')]"
```

## Next steps

- Try a learned judge as the verifier (untested; see "What did not work").
- Put a prompt-only task-type guesser in front of the gateway and test it on prompts written by someone else.
- Re-run the benchmark on a test set that looks like real traffic instead of a knowledge-heavy one.
- Host the small tier somewhere faster than a laptop CPU.
