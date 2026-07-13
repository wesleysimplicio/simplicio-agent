"""Contract tests for simplicio.goal-contract/v1."""

from __future__ import annotations

import json

import pytest

from agent.goal_contract import (
    GOAL_CONTRACT_SCHEMA_VERSION,
    Evidence,
    Fact,
    GoalContract,
    GoalState,
    Inference,
    OpenQuestion,
    VerificationRequiredError,
    WatcherRequirement,
)


def _goal() -> GoalContract:
    return GoalContract.create(
        "ship the release",
        ["tests pass", "receipt is recorded"],
    )


def test_schema_and_hashes_are_stable_and_objective_is_immutable():
    goal = _goal()
    assert goal.to_dict()["schema_version"] == GOAL_CONTRACT_SCHEMA_VERSION
    assert len(goal.objective_hash) == 64
    assert len(goal.acceptance_criteria_hash) == 64
    with pytest.raises(Exception):
        goal.objective = "changed"  # type: ignore[misc]
    assert goal.objective_hash == GoalContract.create("ship the release", ["tests pass", "receipt is recorded"]).objective_hash
    assert goal.ac_hash == goal.acceptance_criteria_hash


def test_structured_facts_inferences_and_questions_round_trip():
    goal = (
        _goal()
        .add_fact(Fact("CI completed", source="ci://run/1", confidence=1.0))
        .add_inference(Inference("release is safe", basis=("CI completed",), confidence=0.9))
        .add_open_question(OpenQuestion("Does product sign-off exist?", blocking=True))
    )
    restored = GoalContract.from_json(goal.to_json())
    assert restored == goal
    assert restored.facts[0].source == "ci://run/1"
    assert restored.inferences[0].basis == ("CI completed",)
    assert restored.open_questions[0].blocking


def test_completed_verified_requires_evidence_and_watcher_recomputation():
    goal = _goal().add_watcher("ci")
    with pytest.raises(VerificationRequiredError):
        goal.mark_completed_verified()
    goal = goal.add_evidence(Evidence("receipt://ci/1", kind="test", verified=True))
    with pytest.raises(VerificationRequiredError):
        goal.mark_completed_verified()
    goal = goal.satisfy_watcher("ci", receipt="receipt://watch/1", recomputed=True)
    completed = goal.mark_completed_verified()
    assert completed.state is GoalState.COMPLETED_VERIFIED
    assert completed.is_terminal and completed.is_complete


def test_unverified_completion_is_honest_and_terminal_states_cannot_resume():
    completed = _goal().mark_completed_unverified(reason="user accepted without receipt")
    assert completed.state is GoalState.COMPLETED_UNVERIFIED
    assert completed.is_terminal
    assert completed.resume() is completed
    with pytest.raises(ValueError):
        completed.transition(GoalState.ACTIVE)


def test_blocked_state_is_resumable_and_not_reported_as_complete():
    blocked = _goal().transition(GoalState.BLOCKED, reason="dependency unavailable")
    assert not blocked.is_terminal and not blocked.is_complete
    assert blocked.resume().state is GoalState.ACTIVE


def test_blocking_question_prevents_verified_completion():
    goal = _goal().add_evidence("receipt://tests").add_open_question("needs approval", blocking=True)
    with pytest.raises(VerificationRequiredError):
        goal.mark_completed_verified()


def test_resumable_serialization_preserves_state_and_rejects_tampering():
    goal = _goal().add_fact("working").transition(GoalState.PAUSED, reason="awaiting CI")
    resumed = GoalContract.from_resume_json(goal.to_resume_json())
    assert resumed == goal
    assert resumed.resume().state is GoalState.ACTIVE
    payload = goal.to_dict()
    payload["objective"] = "tampered"
    with pytest.raises(ValueError):
        GoalContract.from_dict(payload)


def test_fixture_shape_is_json_serializable():
    payload = _goal().to_dict()
    assert json.loads(json.dumps(payload))["objective"] == "ship the release"
