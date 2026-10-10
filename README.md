# LLM Cost Autopilot

Routes every request to the cheapest model that can handle it, then verifies the call was right.

> **Status:** Phase 1 complete (gateway + cascade + logging + tests).
> Router, verifier and benchmark results are in progress.

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

- **Gateway:** FastAPI, `POST /v1/chat/completions`
- **Providers:** LiteLLM (local Ollama models; cloud providers pluggable)
- **Cascade:** tries tiers in order, escalates on error or failed verification
- **Logging:** every request and every attempt (tokens, cost, latency, result)
- **Tests:** pytest with mocked model calls

## Cost model

Prices in `configs/models.yaml` are *reference prices* of comparable paid
models, used to compute **simulated cost** for comparing strategies.
No money is actually spent when running on local models.
Reported savings are relative (e.g. "-X% simulated cost"), not real currency.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
ollama pull llama3.2
ollama pull qwen2.5:7b
uvicorn app.main:app --reload   # then open http://127.0.0.1:8000/docs
python -m pytest -v
```

Optional: copy `.env.example` to `.env` and add API keys for cloud providers.

## Roadmap

- [x] Phase 1: gateway, cascade, SQLite logging, unit tests
- [ ] Phase 2: learned router (rule-based vs classifier vs cascade)
- [ ] Phase 3: task-specific verifiers (schema, code tests, LLM judge)
- [ ] Phase 4: benchmark + cost-vs-quality results

## Known limitations

- Current verifier only checks that the answer is non-empty (placeholder).
- Local models are slower than hosted APIs on CPU.