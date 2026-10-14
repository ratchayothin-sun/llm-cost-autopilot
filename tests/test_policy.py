from unittest.mock import patch

import pytest

from app.router import cascade
from app.router.policy import POLICIES, ROUTES, get_policy, plan_tiers

TIERS3 = [
    {"name": n, "model": f"m/{n}", "input_price_per_1m": 0, "output_price_per_1m": 0}
    for n in ("small", "medium", "large")
]
NAMES = ["small", "medium", "large"]
JSON_PROMPT = [{"role": "user", "content": "Extract JSON with keys a from: 'a is 1'. Return only the JSON."}]
PLAIN_PROMPT = [{"role": "user", "content": "ใครเขียนพระอภัยมณี ตอบสั้นๆ"}]


def fake_result(text, cost=0.001):
    return {"text": text, "prompt_tokens": 1, "completion_tokens": 1, "cost": cost, "latency": 0.1}


def run(messages, side_effect, **kwargs):
    with patch.object(cascade, "TIERS", TIERS3), \
         patch.object(cascade, "call_model", side_effect=side_effect) as call, \
         patch.object(cascade, "log_request"):
        out = cascade.run_cascade(messages, **kwargs)
    return out, call


def test_get_policy_default_is_phase1_cascade(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_POLICY", raising=False)
    assert get_policy().name == "cascade"


def test_get_policy_reads_environment(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_POLICY", "router")
    assert get_policy().name == "router"
    assert get_policy("cascade_format").name == "cascade_format"   # explicit name wins


def test_unknown_policy_raises():
    with pytest.raises(ValueError, match="unknown policy"):
        get_policy("nope")


def test_cascade_plans_every_tier_in_order():
    assert plan_tiers(POLICIES["cascade"], "knowledge", NAMES) == NAMES


def test_router_plans_by_task_type():
    router = POLICIES["router"]
    assert plan_tiers(router, "knowledge", NAMES) == ROUTES["knowledge"] == ["large"]
    assert plan_tiers(router, "extraction", NAMES) == ["small", "medium", "large"]
    assert plan_tiers(router, "math", NAMES) == ["medium", "large"]      # falls to default
    assert plan_tiers(router, None, NAMES) == ["medium", "large"]


def test_plan_drops_missing_tiers_and_never_ends_empty():
    router = POLICIES["router"]
    assert plan_tiers(router, "math", ["small", "medium"]) == ["medium"]
    assert plan_tiers(router, "knowledge", ["small", "medium"]) == ["small", "medium"]


def test_router_sends_knowledge_straight_to_large():
    out, call = run(PLAIN_PROMPT, [fake_result("สุนทรภู่")], task_type="knowledge", policy="router")
    assert out["tier_used"] == "large" and out["escalations"] == 0
    assert call.call_count == 1 and call.call_args.args[0] == "m/large"
    assert out["policy"] == "router"


def test_router_default_route_starts_at_medium():
    out, call = run(PLAIN_PROMPT, [fake_result("ok")], policy="router")
    assert out["tier_used"] == "medium"
    assert call.call_args.args[0] == "m/medium"


def test_router_escalates_extraction_when_json_is_invalid():
    out, _ = run(JSON_PROMPT, [fake_result("a = 1"), fake_result('{"a": 1}')],
                 task_type="extraction", policy="router")
    assert out["tier_used"] == "medium" and out["escalations"] == 1


def test_format_verifier_failure_is_recorded_with_a_reason():
    with patch.object(cascade, "TIERS", TIERS3), \
         patch.object(cascade, "call_model", side_effect=[fake_result("a = 1"), fake_result('{"a": 1}')]), \
         patch.object(cascade, "log_request") as log:
        cascade.run_cascade(JSON_PROMPT, policy="cascade_format")
    attempts = log.call_args.args[2]
    assert [a["verified"] for a in attempts] == [False, True]
    assert attempts[0]["verify_reason"] == "no valid JSON"


def test_last_planned_tier_is_returned_even_if_it_fails_verification():
    out, _ = run(JSON_PROMPT, [fake_result("nope")], task_type="knowledge", policy="router")
    assert out["tier_used"] == "large" and out["text"] == "nope"


def test_default_policy_still_accepts_any_nonempty_small_answer(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_POLICY", raising=False)
    out, call = run(JSON_PROMPT, [fake_result("not json at all")])
    assert out["tier_used"] == "small" and out["policy"] == "cascade"
    assert call.call_count == 1


def test_policy_from_environment_is_used_by_run_cascade(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_POLICY", "router")
    out, _ = run(PLAIN_PROMPT, [fake_result("ok")], task_type="knowledge")
    assert out["tier_used"] == "large"
