"""Focused contracts for the #317 L0-L3 token governor."""

import json
from pathlib import Path

from agent.token_governor import GovernorLevel, TokenGovernor


def _fixture():
    path = (
        Path(__file__).parents[1] / "fixtures" / "native" / "token_governor_routes.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixture_routes_are_deterministic_and_80_percent_remote_free():
    governor = TokenGovernor()
    routes = _fixture()["routes"]
    receipts = [
        governor.route(
            item["id"], **{k: v for k, v in item.items() if k not in {"id", "expected"}}
        )
        for item in routes
    ]
    assert [receipt.level.value for receipt in receipts] == [
        item["expected"] for item in routes
    ]
    assert sum(receipt.remote_free for receipt in receipts) / len(receipts) >= 0.8
    assert all(
        receipt.intent_sha256 not in item["id"]
        for receipt, item in zip(receipts, routes)
    )


def test_l0_l1_have_zero_remote_budget_and_stable_receipts():
    governor = TokenGovernor()
    first = governor.route("inspect config", deterministic=True, entropy=0.0)
    second = governor.route("inspect config", deterministic=True, entropy=0.0)
    assert first.level is GovernorLevel.L1
    assert first.remote_free
    assert first.budget.input_tokens == first.budget.output_tokens == 0
    assert first.to_dict() == second.to_dict()


def test_unavailable_frontier_fails_closed_to_local_route():
    receipt = TokenGovernor().route("ambiguous", entropy=1.0, remote_available=False)
    assert receipt.level is GovernorLevel.L2
    assert receipt.fallback is True
    assert receipt.remote_free
    assert receipt.escalation_reason == "frontier-unavailable-fallback"
