"""Focused tests for issue #138's bounded additive HRM controller contract."""

from __future__ import annotations

import json

import pytest

from agent.hrm_controller_contract import (
    EvidenceStatus,
    HRMController,
    InvalidControllerValue,
    LowLevelMutationError,
    MaxIterationsExceeded,
    Phase,
    Plan,
    PlannerBudgetExceeded,
    ReplanReason,
    StallEscalationError,
)


def _controller(*, planner=None, **overrides: object) -> HRMController:
    values: dict[str, object] = {
        "anchor_hash": "anchor-1",
        "acceptance_criteria_hash": "ac-1",
        "hypothesis": "the bounded step can satisfy the acceptance criteria",
        "max_iterations": 8,
        "planner_call_budget": 8,
        "stall_threshold": 3,
    }
    if planner is not None:
        values["planner"] = planner
    values.update(overrides)
    return HRMController(**values)


def test_start_is_idempotent_and_stable_steps_reuse_the_plan() -> None:
    calls: list[object] = []

    def planner(slow):
        calls.append(slow)
        return Plan(
            phase=slow.phase,
            hypothesis=slow.hypothesis,
            strategy="steady",
            anchor_hash=slow.anchor_hash,
            acceptance_criteria_hash=slow.acceptance_criteria_hash,
            machine_summary="machine-tier plan",
            evidence=("planner receipt",),
        )

    controller = _controller(planner=planner)
    controller.start()
    controller.start()
    controller.execute_step("a")
    controller.execute_step("b")

    assert len(calls) == 1
    assert controller.state.iteration == 2
    assert controller.state.last_replan_reason is ReplanReason.START
    assert controller.receipts[0].status is EvidenceStatus.VERIFIED


def test_false_stall_requires_consecutive_fingerprints() -> None:
    controller = _controller(stall_threshold=3)
    controller.start()
    controller.execute_step("same")
    controller.execute_step("other")
    receipt = controller.execute_step("same")

    assert receipt.transition is None
    assert controller.planner_calls == 1
    assert controller.state.fast.consecutive_fingerprint_count == 1


def test_true_stall_replans_with_a_new_default_strategy() -> None:
    controller = _controller(stall_threshold=2)
    controller.start()
    controller.execute_step("same")
    receipt = controller.execute_step("same")

    assert receipt.transition is not None
    assert receipt.transition.reason is ReplanReason.STALL
    assert controller.planner_calls == 2
    assert controller.state.fast.consecutive_fingerprint_count == 0
    assert controller.plan is not None
    assert controller.plan.strategy == "explore-strategy-2"


def test_stall_replan_must_change_strategy_or_escalate() -> None:
    def planner(slow):
        return Plan(
            phase=slow.phase,
            hypothesis=slow.hypothesis,
            strategy="same",
            anchor_hash=slow.anchor_hash,
            acceptance_criteria_hash=slow.acceptance_criteria_hash,
            machine_summary="same strategy",
            evidence=("receipt",),
        )

    controller = _controller(planner=planner, stall_threshold=2)
    controller.start()
    controller.execute_step("same")
    with pytest.raises(StallEscalationError):
        controller.execute_step("same")


def test_anchor_drift_is_the_only_implicit_replan_from_a_step() -> None:
    controller = _controller()
    controller.start()
    step = controller.execute_step("a", anchor_hash="anchor-2", evidence=("anchor receipt",))

    assert step.transition is not None
    assert step.transition.reason is ReplanReason.ANCHOR_DRIFT
    assert controller.state.anchor_hash == "anchor-2"
    assert controller.planner_calls == 2


def test_low_level_cannot_mutate_phase_or_acceptance_criteria() -> None:
    controller = _controller()
    controller.start()

    with pytest.raises(LowLevelMutationError):
        controller.execute_step("a", phase=Phase.DEBUG)
    with pytest.raises(LowLevelMutationError):
        controller.execute_step("a", acceptance_criteria_hash="ac-2")


def test_explicit_phase_boundary_records_a_deterministic_transition() -> None:
    controller = _controller()
    other = _controller()
    controller.start()
    other.start()
    receipt = controller.phase_boundary(Phase.HARDEN, evidence=("boundary receipt",))
    other.phase_boundary(Phase.HARDEN, evidence=("boundary receipt",))

    assert receipt.reason is ReplanReason.PHASE_BOUNDARY
    assert receipt.to_phase is Phase.HARDEN
    assert controller.state.phase is Phase.HARDEN
    assert controller.state.to_json() == other.state.to_json()
    assert controller.receipts[1].to_dict() == other.receipts[1].to_dict()


def test_max_iterations_and_planner_budget_fail_closed() -> None:
    controller = _controller(max_iterations=1)
    controller.start()
    controller.execute_step("a")
    with pytest.raises(MaxIterationsExceeded):
        controller.execute_step("b")

    budgeted = _controller(planner_call_budget=1)
    budgeted.start()
    with pytest.raises(PlannerBudgetExceeded):
        budgeted.phase_boundary(Phase.DEBUG, evidence=("boundary",))


def test_receipts_and_state_are_deterministic_and_inferred_is_unverified() -> None:
    def inferred_planner(slow):
        return Plan(
            phase=slow.phase,
            hypothesis=slow.hypothesis,
            strategy=f"strategy-{slow.planner_calls + 1}",
            anchor_hash=slow.anchor_hash,
            acceptance_criteria_hash=slow.acceptance_criteria_hash,
            machine_summary="inferred machine summary",
            inferred=True,
        )

    first = _controller(planner=inferred_planner)
    second = _controller(planner=inferred_planner)
    first.start()
    second.start()

    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["receipts"][0]["status"] == "UNVERIFIED"
    assert first.machine_summary()["phase"] == "explore"
    assert "transcript" not in first.machine_summary()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"anchor_hash": ""},
        {"acceptance_criteria_hash": "bad hash"},
        {"max_iterations": True},
        {"planner_call_budget": 0},
        {"stall_threshold": 0},
        {"phase": "unknown"},
        {"hypothesis": "\nunsafe"},
        {"planner": object()},
    ],
)
def test_invalid_values_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidControllerValue):
        _controller(**kwargs)
