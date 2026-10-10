from pathlib import Path
import yaml

from app.providers.client import call_model
from app.logging_db.logger import log_request

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "models.yaml"
TIERS = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["tiers"]


def simple_verify(messages, response_text: str) -> bool:
    return bool(response_text and response_text.strip())


def run_cascade(messages, task_type=None):
    attempts = []
    for tier in TIERS:
        try:
            result = call_model(tier["model"], messages, tier)
        except Exception as e:
            print(f"[tier {tier['name']}] failed: {e}")
            attempts.append({
                "tier": tier["name"], "model": tier["model"], "text": "",
                "prompt_tokens": 0, "completion_tokens": 0,
                "cost": 0.0, "latency": 0.0, "verified": False,
                "error": str(e),
            })
            continue

        ok = simple_verify(messages, result["text"])
        attempts.append({**result, "tier": tier["name"],
                         "model": tier["model"], "verified": ok})
        if ok:
            break

    log_request(messages, task_type, attempts)
    final = attempts[-1]
    return {
        "text": final["text"],
        "tier_used": final["tier"],
        "total_cost": sum(a["cost"] for a in attempts),
        "escalations": len(attempts) - 1,
    }