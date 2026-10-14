from pathlib import Path

import yaml

from app.providers.client import call_model
from app.logging_db.logger import log_request
from app.router import verifiers
from app.router.policy import Policy, get_policy, plan_tiers

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "models.yaml"
TIERS = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["tiers"]


def simple_verify(messages, response_text: str) -> bool:
    """Phase 1 verifier: the answer is not empty."""
    return bool(verifiers.nonempty(messages, response_text))


def run_cascade(messages, task_type=None, policy=None):
    """Try the tiers a policy plans, cheapest first, until one answer passes verification.

    policy: a Policy, a policy name, or None (then $AUTOPILOT_POLICY, default 'cascade',
    which reproduces Phase 1: every tier in order, accept any non-empty answer).
    The last planned tier's answer is returned even if it fails verification.
    """
    if not isinstance(policy, Policy):
        policy = get_policy(policy)
    verify = verifiers.VERIFIERS[policy.verifier]
    by_name = {t["name"]: t for t in TIERS}

    attempts = []
    for name in plan_tiers(policy, task_type, list(by_name)):
        tier = by_name[name]
        try:
            result = call_model(tier["model"], messages, tier)
        except Exception as e:
            attempts.append({
                "tier": tier["name"], "model": tier["model"], "text": "",
                "prompt_tokens": 0, "completion_tokens": 0,
                "cost": 0.0, "latency": 0.0, "verified": False,
                "verify_reason": "error", "error": str(e),
            })
            continue

        verdict = verify(messages, result["text"])
        ok = bool(verdict)
        attempts.append({**result, "tier": tier["name"], "model": tier["model"],
                         "verified": ok,
                         "verify_reason": getattr(verdict, "reason", "")})
        if ok:
            break

    log_request(messages, task_type, attempts)
    final = attempts[-1]
    return {
        "text": final["text"],
        "tier_used": final["tier"],
        "total_cost": sum(a["cost"] for a in attempts),
        "escalations": len(attempts) - 1,
        "policy": policy.name,
    }
