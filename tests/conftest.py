import pytest


@pytest.fixture(autouse=True)
def _no_ambient_policy(monkeypatch):
    """run_cascade reads AUTOPILOT_POLICY when it is called. A shell that still has
    $env:AUTOPILOT_POLICY = "router" from running the gateway would silently change
    what the tests exercise, so every test starts without it. Tests that need a
    policy pass `policy=` or set the variable themselves."""
    monkeypatch.delenv("AUTOPILOT_POLICY", raising=False)
