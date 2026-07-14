"""Focused contract tests for the bounded J-Space slice."""

from __future__ import annotations

import json

import pytest

from agent.jspace_contract import (
    AXES,
    SCHEMA,
    JSpaceState,
    JSpaceTrajectory,
    JSpaceTransition,
    RecallMetadata,
    Receipt,
    RoutingMetadata,
    canonical_json,
    content_hash,
)


def make_state(progress: float = 0.25) -> JSpaceState:
    return JSpaceState(
        task_progress=progress,
        uncertainty=0.2,
        resource_pressure=0.1,
        safety_risk=0.05,
        evidence_coverage=0.8,
        memory_novelty=0.4,
        phase="implement",
        authorization="approved",
        routing=RoutingMetadata(
            requested_capability="python-edit",
            candidate_ids=("dev-cli", "local"),
            selected_id="dev-cli",
            reason="bounded file target",
        ),
        recall=RecallMetadata(
            query_hash="query:abc",
            corpus_id="precedent:v1",
            candidate_ids=("precedent-1",),
            selected_ids=("precedent-1",),
            mode="nearest-success",
            evidence_receipt="receipt:recall",
        ),
    )


def make_transition(before: JSpaceState, after: JSpaceState) -> JSpaceTransition:
    return JSpaceTransition(
        before=before,
        after=after,
        action="apply bounded patch",
        anchor_hash="anchor:abc",
        receipt=Receipt(kind="pytest", value="focused contract passed"),
        cause="acceptance criterion",
    )


def test_state_is_typed_and_separates_measured_from_unverified() -> None:
    state = make_state()

    assert state.to_dict()["schema"] == SCHEMA
    assert state.measured == AXES
    assert state.observed == AXES
    assert state.unverified == ()
    assert state.inferred == ()
    assert isinstance(state.content_hash, str)
    assert len(state.state_id) == len("state:") + 64


def test_state_rejects_invalid_axis_values_and_provenance_overlap() -> None:
    with pytest.raises(ValueError, match="task_progress"):
        make_state(progress=1.1)

    with pytest.raises(ValueError, match="both measured and unverified"):
        JSpaceState(
            task_progress=0.0,
            uncertainty=0.0,
            resource_pressure=0.0,
            safety_risk=0.0,
            evidence_coverage=0.0,
            memory_novelty=0.0,
            phase="observe",
            authorization="unknown",
            measured=AXES,
            unverified=("phase",),
        )

    inferred = JSpaceState(
        task_progress=0.0,
        uncertainty=0.0,
        resource_pressure=0.0,
        safety_risk=0.0,
        evidence_coverage=0.0,
        memory_novelty=0.0,
        phase="observe",
        authorization="unknown",
        measured=AXES[:-2],
        unverified=("phase", "authorization"),
    )
    assert inferred.observed == AXES[:-2]
    assert inferred.inferred == ("phase", "authorization")
    assert inferred.task_progress == 0.0


def test_canonical_json_and_hash_are_order_independent() -> None:
    left = {"b": [2, 1], "a": {"z": "é", "x": True}}
    right = {"a": {"x": True, "z": "é"}, "b": [2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert content_hash(left) == content_hash(right)
    assert json.loads(make_state().canonical_json)["schema"] == SCHEMA


def test_trajectory_id_content_hash_and_replay_are_deterministic() -> None:
    initial = make_state()
    after = make_state(progress=0.75)
    transition = make_transition(initial, after)
    first = JSpaceTrajectory(initial, (transition,))
    second = JSpaceTrajectory(make_state(), (make_transition(make_state(), make_state(0.75)),))

    assert first.trajectory_id == second.trajectory_id
    assert first.content_hash == second.content_hash
    assert first.replay() == (initial, after)
    assert first.verify_reproducibility()
    assert first.verify_reproducibility().replay_hash == content_hash(first.states)
    assert first.canonical_bytes == first.canonical_json.encode("utf-8")


def test_append_preserves_chain_and_rejects_disconnected_transition() -> None:
    initial = make_state()
    middle = make_state(progress=0.5)
    final = make_state(progress=1.0)
    trajectory = JSpaceTrajectory(initial).append(make_transition(initial, middle))
    extended = trajectory.append(make_transition(middle, final))

    assert extended.states == (initial, middle, final)
    assert len(extended.transitions) == 2
    extended.assert_reproducible()

    with pytest.raises(ValueError, match="trajectory tail"):
        trajectory.append(make_transition(initial, final))


def test_transition_contains_routing_recall_and_receipt_evidence() -> None:
    state = make_state()
    transition = make_transition(state, make_state(0.5))
    payload = transition.to_dict()

    assert payload["before"].routing.selected_id == "dev-cli"
    assert payload["after"].recall.mode == "nearest-success"
    assert payload["receipt"].kind == "pytest"
    assert len(transition.content_hash) == 64
