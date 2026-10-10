from unittest.mock import patch

import pytest

from app.router import cascade

FAKE_TIERS = [
    {"name": "small", "model": "m/small",
     "input_price_per_1m": 0, "output_price_per_1m": 0},
    {"name": "medium", "model": "m/medium",
     "input_price_per_1m": 0, "output_price_per_1m": 0},
]
MESSAGES = [{"role": "user", "content": "hi"}]


def fake_result(text, cost=0.001):
    return {"text": text, "prompt_tokens": 10, "completion_tokens": 5,
            "cost": cost, "latency": 0.1}


def run(side_effect):
    with patch.object(cascade, "TIERS", FAKE_TIERS), \
         patch.object(cascade, "call_model", side_effect=side_effect), \
         patch.object(cascade, "log_request") as log:
        out = cascade.run_cascade(MESSAGES)
    return out, log


def test_small_tier_succeeds_no_escalation():
    out, _ = run([fake_result("ok")])
    assert out["tier_used"] == "small"
    assert out["escalations"] == 0


def test_escalates_when_small_raises():
    out, _ = run([RuntimeError("provider down"), fake_result("ok")])
    assert out["tier_used"] == "medium"
    assert out["escalations"] == 1


def test_escalates_when_small_returns_empty():
    out, _ = run([fake_result("   "), fake_result("ok")])
    assert out["tier_used"] == "medium"
    assert out["escalations"] == 1


def test_total_cost_includes_failed_attempts():
    out, _ = run([fake_result("", cost=0.002), fake_result("ok", cost=0.010)])
    assert out["total_cost"] == pytest.approx(0.012)


def test_all_tiers_fail_returns_without_crashing():
    out, log = run([RuntimeError("a"), RuntimeError("b")])
    assert out["text"] == ""
    assert out["escalations"] == 1
    log.assert_called_once()