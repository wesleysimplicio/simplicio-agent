"""Focused contracts for the #317 L0-L3 token governor."""

import json
from pathlib import Path

import pytest

from agent.telemetry.receipts import lookup_receipt
from agent.token_governor import (
    GovernorLevel,
    TokenGovernor,
    TurnBudget,
    record_route_receipt,
)


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


def test_route_receipt_is_content_free_and_uses_append_only_telemetry(
    tmp_path: Path,
) -> None:
    receipt = TokenGovernor().route(
        "private intent that must not be persisted", deterministic=True
    )

    recorded = record_route_receipt(receipt, directory=tmp_path)
    loaded = lookup_receipt(receipt.canonical_json(), directory=tmp_path)

    assert loaded == recorded
    assert recorded.yool_id == "agent.token.governor"
    assert recorded.cost.tokens == 0
    assert recorded.meta["schema"] == "simplicio.agent.token-governor/v1"
    payload = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "private intent" not in payload
    assert receipt.canonical_json() == receipt.canonical_json()


def test_route_and_record_returns_same_local_decision(tmp_path: Path) -> None:
    receipt, telemetry = TokenGovernor().route_and_record(
        "cached", cache_hit=True, directory=tmp_path
    )

    assert receipt.level is GovernorLevel.L0
    assert telemetry.status == "cached"
    assert telemetry.cost.tokens == 0


def test_zero_remote_levels_reject_nonzero_custom_budgets() -> None:
    budgets = {
        GovernorLevel.L0: TurnBudget(1, 0, 0),
        GovernorLevel.L1: TurnBudget(0, 0, 0),
        GovernorLevel.L2: TurnBudget(1, 1, 1),
        GovernorLevel.L3: TurnBudget(1, 1, 1),
    }
    with pytest.raises(ValueError, match="entirely zero"):
        TokenGovernor(budgets=budgets)


def test_intent_must_be_text() -> None:
    with pytest.raises(TypeError, match="intent must be text"):
        TokenGovernor().route(None)  # type: ignore[arg-type]
