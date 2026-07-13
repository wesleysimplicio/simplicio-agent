"""Tests for TaskEnvelope/v1 schema + state machine (issue #209)."""

from __future__ import annotations

import pytest

from agent.task_envelope import (
    InvalidTransitionError,
    TASK_ENVELOPE_SCHEMA_VERSION,
    TaskEnvelope,
    TaskLedger,
    TaskState,
)


def _make(**overrides):
    defaults = dict(
        repo="simplicio-agent",
        branch="issue-209",
        scope="agent/task_envelope.py",
        acceptance_criteria=["schema exists", "transitions validated"],
    )
    defaults.update(overrides)
    return TaskEnvelope.create(**defaults)


def test_new_envelope_has_pinned_schema_and_starts_received():
    env = _make()
    assert env.schema_version == TASK_ENVELOPE_SCHEMA_VERSION
    assert env.state is TaskState.RECEIVED
    assert env.attempts == 0
    assert env.evidence_refs == ()


def test_dict_and_json_round_trip_every_field():
    env = _make().transition(TaskState.ORIENTED)
    restored = TaskEnvelope.from_dict(env.to_dict())
    assert restored == env
    again = TaskEnvelope.from_json(env.to_json())
    assert again == env


def test_unknown_state_in_from_dict_is_rejected():
    data = _make().to_dict()
    data["state"] = "teleported"
    with pytest.raises(ValueError):
        TaskEnvelope.from_dict(data)


def test_wrong_schema_version_is_rejected():
    data = _make().to_dict()
    data["schema_version"] = "simplicio.task-envelope/v0"
    with pytest.raises(ValueError):
        TaskEnvelope.from_dict(data)


def test_wrong_schema_id_is_rejected():
    data = _make().to_dict()
    data["schema"] = "other.task-envelope"
    with pytest.raises(ValueError):
        TaskEnvelope.from_dict(data)


def test_transition_accepts_wire_state_value_and_rejects_unknown_state():
    env = _make().transition("oriented")
    assert env.state is TaskState.ORIENTED
    with pytest.raises(ValueError, match="invalid state"):
        env.transition("teleported")


# ---------------------------------------------------------------------------
# E2E happy path: received -> ... -> evidence_ready -> delivered -> closed
# ---------------------------------------------------------------------------


def test_e2e_happy_path_to_closed_with_evidence():
    env = _make()
    for state in (
        TaskState.ORIENTED,
        TaskState.PLANNED,
        TaskState.CLAIMED,
        TaskState.EXECUTING,
        TaskState.VALIDATING,
    ):
        env = env.transition(state)
    env = env.transition(TaskState.EVIDENCE_READY, evidence_refs=["receipt://test-run-1"])
    env = env.transition(TaskState.DELIVERED, delivery_target="pr://simplicio-agent/999")
    env = env.transition(TaskState.CLOSED)

    assert env.state is TaskState.CLOSED
    assert env.is_terminal
    assert env.evidence_refs == ("receipt://test-run-1",)
    assert env.delivery_target == "pr://simplicio-agent/999"
    # EXECUTING was entered exactly once along this path.
    assert env.attempts == 1


def test_closed_refuses_without_evidence_receipt():
    env = _make()
    for state in (
        TaskState.ORIENTED,
        TaskState.PLANNED,
        TaskState.CLAIMED,
        TaskState.EXECUTING,
        TaskState.VALIDATING,
        TaskState.EVIDENCE_READY,
        TaskState.DELIVERED,
    ):
        env = env.transition(state)
    assert env.evidence_refs == ()
    with pytest.raises(ValueError):
        env.transition(TaskState.CLOSED)


# ---------------------------------------------------------------------------
# Invalid transitions are rejected deterministically
# ---------------------------------------------------------------------------


def test_invalid_transition_is_rejected_deterministically():
    env = _make()  # RECEIVED
    with pytest.raises(InvalidTransitionError) as exc_info:
        env.transition(TaskState.DELIVERED)
    assert "received" in str(exc_info.value)
    assert "delivered" in str(exc_info.value)


def test_terminal_states_have_no_outgoing_transitions():
    env = _make().transition(TaskState.ORIENTED).transition(TaskState.CANCELLED)
    assert env.is_terminal
    with pytest.raises(InvalidTransitionError):
        env.transition(TaskState.PLANNED)


def test_blocked_can_resume_into_canonical_chain():
    env = _make().transition(TaskState.ORIENTED).transition(
        TaskState.BLOCKED, block_reason="waiting on dependency"
    )
    assert env.block_reason == "waiting on dependency"
    resumed = env.transition(TaskState.PLANNED)
    assert resumed.state is TaskState.PLANNED
    assert resumed.block_reason is None


# ---------------------------------------------------------------------------
# Idempotency: repeating the same event does not duplicate state or evidence
# ---------------------------------------------------------------------------


def test_same_state_transition_is_idempotent_noop():
    env = _make().transition(TaskState.ORIENTED)
    same = env.transition(TaskState.ORIENTED)
    assert same is env
    assert same.updated_at_ns == env.updated_at_ns


def test_repeated_executing_event_does_not_duplicate_attempts():
    env = _make().transition(TaskState.ORIENTED).transition(TaskState.PLANNED).transition(
        TaskState.CLAIMED
    )
    env = env.transition(TaskState.EXECUTING)
    assert env.attempts == 1
    same = env.transition(TaskState.EXECUTING)  # duplicate event, same state
    assert same.attempts == 1


def test_repeated_evidence_ref_is_not_duplicated():
    env = _make()
    for state in (
        TaskState.ORIENTED,
        TaskState.PLANNED,
        TaskState.CLAIMED,
        TaskState.EXECUTING,
        TaskState.VALIDATING,
    ):
        env = env.transition(state)
    env = env.transition(TaskState.EVIDENCE_READY, evidence_refs=["receipt://a"])
    env = env.transition(TaskState.EVIDENCE_READY, evidence_refs=["receipt://a"])
    assert env.evidence_refs == ("receipt://a",)


# ---------------------------------------------------------------------------
# Ledger: task_id + envelope hash per transition
# ---------------------------------------------------------------------------


def test_ledger_records_task_id_and_hash_per_transition():
    ledger = TaskLedger()
    env = _make()
    ledger.append(env)
    env = env.transition(TaskState.ORIENTED)
    ledger.append(env)

    history = ledger.history(env.task_id)
    assert len(history) == 2
    assert all(r["task_id"] == env.task_id for r in history)
    assert history[0]["envelope_hash"] != history[1]["envelope_hash"]
    assert history[1]["state"] == "oriented"


def test_ledger_append_is_idempotent_for_duplicate_content():
    ledger = TaskLedger()
    env = _make()
    ledger.append(env)
    ledger.append(env)  # exact same content, appended twice
    assert len(ledger.history(env.task_id)) == 1
