"""Routing policies: which tiers to try (in order) and how to verify each answer.

A policy is data, so the gateway (cascade.py) and the offline replay
(eval/replay.py) run exactly the same definition.

The ROUTES table below was written after looking at the dev split, so its
numbers are in-sample until the test split has been run once. See README.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Sequence

# task_type -> tiers to try, cheapest first. "default" covers a missing or unknown task_type.
#  knowledge  : medium made confident factual mistakes on Thai general knowledge in dev,
#               so go straight to the large tier.
#  extraction : structured output has a cheap, reliable check (valid JSON), so try the
#               small tier first and let the verifier escalate.
ROUTES = {
    "knowledge": ["large"],
    "extraction": ["small", "medium", "large"],
    "default": ["medium", "large"],
}


@dataclass(frozen=True)
class Policy:
    name: str
    verifier: str                       # key into app.router.verifiers.VERIFIERS
    routes: Optional[dict] = None       # None = try every tier in configured order


POLICIES = {
    # Phase 1 behaviour: small -> medium -> large, accept anything non-empty.
    "cascade": Policy("cascade", "nonempty"),
    # Same order, but reject answers that ignore explicit format instructions.
    "cascade_format": Policy("cascade_format", "format"),
    # Route by task_type, then verify the format.
    "router": Policy("router", "format", ROUTES),
}
DEFAULT_POLICY = "cascade"


def get_policy(name: Optional[str] = None) -> Policy:
    """Resolve a policy by name; falls back to $AUTOPILOT_POLICY, then 'cascade'."""
    name = name or os.getenv("AUTOPILOT_POLICY") or DEFAULT_POLICY
    try:
        return POLICIES[name]
    except KeyError:
        raise ValueError(f"unknown policy {name!r}; choose one of {sorted(POLICIES)}") from None


def plan_tiers(policy: Policy, task_type: Optional[str], available: Sequence[str]) -> list:
    """Tier names to try, in order. Names missing from `available` are dropped;
    if nothing is left, every available tier is tried in order."""
    available = list(available)
    if policy.routes is None:
        return available
    wanted = policy.routes.get(task_type or "", policy.routes["default"])
    planned = [n for n in wanted if n in available]
    return planned or available
