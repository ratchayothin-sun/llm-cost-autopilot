import time

from litellm import completion


def call_model(model: str, messages: list[dict], price: dict) -> dict:
    # Per-tier call options live in configs/models.yaml under `params`
    # (temperature, max_tokens, reasoning_effort, ...). Local Ollama models also get
    # a fixed seed so runs are repeatable.
    extra = dict(price.get("params") or {})
    if model.startswith("ollama/"):
        extra.setdefault("temperature", 0)
        extra.setdefault("seed", 42)

    start = time.perf_counter()
    resp = completion(model=model, messages=messages, timeout=120, **extra)
    latency = time.perf_counter() - start

    usage = resp.usage
    cost = (usage.prompt_tokens * price["input_price_per_1m"]
            + usage.completion_tokens * price["output_price_per_1m"]) / 1_000_000

    return {
        # a model that runs out of tokens while "thinking" returns no text
        "text": resp.choices[0].message.content or "",
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost": cost,
        "latency": latency,
    }