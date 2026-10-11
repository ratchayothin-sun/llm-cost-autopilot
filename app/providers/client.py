import time

from litellm import completion


def call_model(model: str, messages: list[dict], price: dict) -> dict:
    # Make local models reproducible; leave cloud models at their defaults.
    extra = {}
    if model.startswith("ollama/"):
        extra = {"temperature": 0, "seed": 42}

    start = time.perf_counter()
    resp = completion(model=model, messages=messages, timeout=120, **extra)
    latency = time.perf_counter() - start

    usage = resp.usage
    cost = (usage.prompt_tokens * price["input_price_per_1m"]
            + usage.completion_tokens * price["output_price_per_1m"]) / 1_000_000

    return {
        "text": resp.choices[0].message.content,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost": cost,
        "latency": latency,
    }