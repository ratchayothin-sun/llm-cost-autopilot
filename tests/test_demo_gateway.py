import json

import httpx

from eval import demo_gateway


def fake_gateway(policy="router", tier="medium", escalations=0):
    """An httpx transport that answers like the gateway, recording what it was sent."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={
            "text": "ok\nline two", "tier_used": tier, "total_cost": 0.5,
            "escalations": escalations, "policy": policy})

    return httpx.MockTransport(handler), seen


def run(policy="router", tier="medium", escalations=0):
    transport, seen = fake_gateway(policy, tier, escalations)
    with httpx.Client(transport=transport) as client:
        rows = demo_gateway.run_demo(client, "http://gateway")
    return rows, seen


def test_run_demo_sends_task_type_and_messages():
    rows, seen = run()
    assert len(rows) == len(demo_gateway.REQUESTS) == len(seen)
    assert seen[0]["task_type"] == "knowledge"
    assert seen[0]["messages"][0]["role"] == "user"
    assert seen[-1]["task_type"] is None            # requests without a task_type send null
    assert rows[0]["text"] == "ok line two"         # newlines flattened for the table


def test_policy_warning_only_when_router_is_not_active():
    assert demo_gateway.policy_warning(run("router")[0]) is None
    assert "cascade" in demo_gateway.policy_warning(run("cascade")[0])


def test_table_flags_unexpected_tiers_and_sums_cost():
    table = demo_gateway.format_table(run(tier="medium")[0])
    assert "(expected large)" in table              # knowledge rows should have gone to large
    assert "(expected medium)" not in table
    assert f"{0.5 * len(demo_gateway.REQUESTS):10.6f}" in table


def test_escalated_requests_are_not_flagged_as_unexpected():
    table = demo_gateway.format_table(run(tier="medium", escalations=1)[0])
    assert "(expected" not in table
