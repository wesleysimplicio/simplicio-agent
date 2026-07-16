"""Tests for the TaskEnvelope <-> protocol_v1 bridge (issue #209 step 6/9)."""

from __future__ import annotations

import pytest

from agent.protocol_v1 import Emitter, LifecycleEvent
from agent.task_envelope import InvalidTransitionError, TaskEnvelope, TaskState
from agent.task_envelope_bridge import emit_for_transition


def _new_envelope() -> TaskEnvelope:
    return TaskEnvelope.create(
        repo="simplicio-agent",
        branch="main",
        scope="issue-209",
        acceptance_criteria=["schema exists"],
    )


def test_every_transition_emits_exactly_one_protocol_event():
    envelope = _new_envelope()
    emitter = Emitter(session_id="s1")
    turn_id = "t1"

    chain = [
        TaskState.ORIENTED,
        TaskState.PLANNED,
        TaskState.CLAIMED,
        TaskState.EXECUTING,
        TaskState.VALIDATING,
        TaskState.EVIDENCE_READY,
        TaskState.DELIVERED,
    ]
    emitted = []
    for state in chain:
        after = envelope.transition(state)
        evt = emit_for_transition(envelope, after, emitter, turn_id=turn_id)
        assert evt is not None
        emitted.append(evt)
        envelope = after

    closed = envelope.transition(TaskState.CLOSED, evidence_refs=["receipt-1"])
    evt = emit_for_transition(envelope, closed, emitter, turn_id=turn_id)
    emitted.append(evt)

    assert [e.seq for e in emitted] == list(range(1, len(emitted) + 1))
    assert emitted[-1].event_type == LifecycleEvent.COMPLETED.value
    assert emitted[3].event_type == LifecycleEvent.STARTED.value


def test_same_state_transition_emits_no_duplicate_event():
    envelope = _new_envelope()
    emitter = Emitter(session_id="s1")

    same = envelope.transition(TaskState.RECEIVED)
    evt = emit_for_transition(envelope, same, emitter, turn_id="t1")

    assert same is envelope
    assert evt is None


def test_mismatched_task_id_is_rejected():
    a = _new_envelope()
    b = _new_envelope()
    emitter = Emitter(session_id="s1")

    with pytest.raises(ValueError):
        emit_for_transition(a, b, emitter, turn_id="t1")


def test_bridge_rejects_forged_jump_even_when_task_id_matches():
    envelope = _new_envelope()
    forged = envelope.transition(TaskState.ORIENTED).transition(TaskState.PLANNED)
    # A caller must emit each committed transition in order; passing a later
    # snapshot directly must not bypass the state machine.
    with pytest.raises(InvalidTransitionError):
        emit_for_transition(envelope, forged, Emitter(session_id="s1"), turn_id="t1")


def test_bridge_rejects_same_state_metadata_changes_instead_of_silently_nooping():
    envelope = _new_envelope()
    forged = envelope.transition(TaskState.ORIENTED)
    # Same-state replay is only idempotent when it is the exact same envelope.
    forged = TaskEnvelope.from_dict({
        **forged.to_dict(),
        "receipts": ["receipt://forged"],
    })
    with pytest.raises(ValueError, match="same-state transition"):
        emit_for_transition(
            envelope.transition(TaskState.ORIENTED),
            forged,
            Emitter(session_id="s1"),
            turn_id="t1",
        )


def test_bridge_rejects_lineage_changes_on_an_otherwise_legal_transition():
    before = _new_envelope()
    after = before.transition(TaskState.ORIENTED)
    forged = TaskEnvelope.from_dict({**after.to_dict(), "scope": "other-task"})

    with pytest.raises(ValueError, match="lineage mismatch"):
        emit_for_transition(before, forged, Emitter(session_id="s1"), turn_id="t1")


def test_bridge_rejects_forged_receipt_removal_and_attempt_count():
    before = _new_envelope().transition(TaskState.ORIENTED)
    before = before.transition(TaskState.PLANNED, receipts=["receipt://plan"])
    after = TaskEnvelope.from_dict({
        **before.to_dict(),
        "state": TaskState.CLAIMED.value,
        "receipts": [],
    })

    with pytest.raises(ValueError, match="receipts cannot be removed"):
        emit_for_transition(before, after, Emitter(session_id="s1"), turn_id="t1")


def test_bridge_rejects_reordered_refs_and_delivery_metadata_changes():
    before = _new_envelope().transition(TaskState.ORIENTED, receipts=["receipt://a"])
    before = before.transition(TaskState.PLANNED, receipts=["receipt://b"])
    reordered = TaskEnvelope.from_dict(
        {
            **before.to_dict(),
            "state": TaskState.CLAIMED.value,
            "receipts": ["receipt://b", "receipt://a"],
        }
    )
    with pytest.raises(ValueError, match="append-only"):
        emit_for_transition(before, reordered, Emitter(session_id="s1"), turn_id="t1")

    delivered = _new_envelope()
    for state in (
        TaskState.ORIENTED,
        TaskState.PLANNED,
        TaskState.CLAIMED,
        TaskState.EXECUTING,
        TaskState.VALIDATING,
    ):
        delivered = delivered.transition(state)
    delivered = delivered.transition(
        TaskState.EVIDENCE_READY,
        evidence_refs=["receipt://bridge"],
    )
    delivered = delivered.transition(
        TaskState.DELIVERED,
        delivery_target="pr://original",
    )
    forged = TaskEnvelope.from_dict(
        {**delivered.to_dict(), "state": TaskState.CLOSED.value, "delivery_target": "pr://forged"}
    )
    with pytest.raises(ValueError, match="delivery_target cannot be changed"):
        emit_for_transition(delivered, forged, Emitter(session_id="s1"), turn_id="t1")


def test_failed_and_quarantined_both_map_to_failed_lifecycle_event():
    envelope = _new_envelope().transition(TaskState.ORIENTED)
    emitter = Emitter(session_id="s1")

    failed = envelope.transition(TaskState.FAILED)
    evt_failed = emit_for_transition(envelope, failed, emitter, turn_id="t1")

    quarantined = envelope.transition(TaskState.QUARANTINED)
    evt_quarantined = emit_for_transition(envelope, quarantined, emitter, turn_id="t2")

    assert evt_failed.event_type == LifecycleEvent.FAILED.value
    assert evt_quarantined.event_type == LifecycleEvent.FAILED.value


def test_e2e_vertical_slice_received_to_closed_produces_matching_event_trail():
    """AC: chat/CLI/workflow/worker should all produce the same canonical
    envelope + emit the same lifecycle trail — this is the smallest real
    vertical slice: one caller drives both envelope + protocol_v1 together."""
    envelope = _new_envelope()
    emitter = Emitter(session_id="session-e2e")
    turn_id = "turn-e2e"
    trail = []

    for state, kwargs in [
        (TaskState.ORIENTED, {}),
        (TaskState.PLANNED, {}),
        (TaskState.CLAIMED, {"worker": "worker-1", "lease": "lease-1"}),
        (TaskState.EXECUTING, {}),
        (TaskState.VALIDATING, {}),
        (TaskState.EVIDENCE_READY, {"evidence_refs": ["pytest://ok"]}),
        (TaskState.DELIVERED, {"delivery_target": "pr://123"}),
        (TaskState.CLOSED, {}),
    ]:
        after = envelope.transition(state, **kwargs)
        evt = emit_for_transition(envelope, after, emitter, turn_id=turn_id)
        trail.append((after.state, evt.event_type))
        envelope = after

    assert envelope.state is TaskState.CLOSED
    assert envelope.evidence_refs == ("pytest://ok",)
    assert trail[-1] == (TaskState.CLOSED, LifecycleEvent.COMPLETED.value)
    assert len(trail) == 8
