"""Bridge from :mod:`agent.task_envelope` transitions to :mod:`agent.protocol_v1`
lifecycle events.

Issue #209 step 6/9: ``TaskEnvelope`` is the durable *state* of a task; a
``protocol_v1.Envelope`` is the UI/audit-facing *event* about a moment in that
state. They must not become two competing models of "what happened" — every
``TaskEnvelope.transition(...)`` that a control plane commits should also emit
exactly one causal ``protocol_v1.Envelope`` so downstream consumers (CLI,
gateway, TUI, ACP) keep seeing the same lifecycle they already understand,
without reading ``task_envelope`` directly.

This module owns the (deterministic, one-directional) mapping
:data:`STATE_TO_EVENT_TYPE` and the single entry point
:func:`emit_for_transition`. It never constructs a ``TaskEnvelope`` and never
mutates one — callers pass the envelope *before* and *after* a transition and
get back the ``protocol_v1.Envelope`` (or ``None`` for a same-state / no-op
transition, matching ``TaskEnvelope.transition``'s own idempotency).
"""

from __future__ import annotations

from typing import Dict, Optional

from agent.protocol_v1 import Emitter, Envelope, ExecutionEvent, LifecycleEvent
from agent.task_envelope import (
    InvalidTransitionError,
    TaskEnvelope,
    TaskState,
    is_transition_allowed,
)

#: Deterministic map from a ``TaskEnvelope`` state to the ``protocol_v1``
#: event_type that represents "the task just entered this state". States not
#: present here (there are none — every ``TaskState`` member is mapped) would
#: raise ``KeyError`` rather than silently drop the event.
STATE_TO_EVENT_TYPE: Dict[TaskState, str] = {
    TaskState.RECEIVED: LifecycleEvent.ACCEPTED.value,
    TaskState.ORIENTED: ExecutionEvent.CHECKPOINT.value,
    TaskState.PLANNED: ExecutionEvent.CHECKPOINT.value,
    TaskState.CLAIMED: ExecutionEvent.CHECKPOINT.value,
    TaskState.EXECUTING: LifecycleEvent.STARTED.value,
    TaskState.VALIDATING: ExecutionEvent.CHECKPOINT.value,
    TaskState.EVIDENCE_READY: ExecutionEvent.CHECKPOINT.value,
    TaskState.DELIVERED: ExecutionEvent.CHECKPOINT.value,
    TaskState.CLOSED: LifecycleEvent.COMPLETED.value,
    TaskState.BLOCKED: LifecycleEvent.PAUSED.value,
    TaskState.CANCELLED: LifecycleEvent.CANCELLED.value,
    TaskState.QUARANTINED: LifecycleEvent.FAILED.value,
    TaskState.FAILED: LifecycleEvent.FAILED.value,
}

assert set(STATE_TO_EVENT_TYPE) == set(TaskState), (
    "every TaskState must have a protocol_v1 event mapping"
)

# These fields identify the task itself, rather than the mutable state carried
# by a transition.  The bridge is a trust boundary: callers may only emit an
# event for a successor produced from the same task lineage.  In particular,
# accepting a ``dataclasses.replace``d envelope here would let a worker forge a
# protocol event without going through ``TaskEnvelope.transition``.
_LINEAGE_FIELDS = (
    "schema",
    "schema_version",
    "task_id",
    "parent_id",
    "correlation_id",
    "repo",
    "branch",
    "scope",
    "write_set",
    "acceptance_criteria",
    "risk_policy",
    "model",
    "execution_policy",
    "created_at_ns",
)


def emit_for_transition(
    before: TaskEnvelope,
    after: TaskEnvelope,
    emitter: Emitter,
    *,
    turn_id: str,
    attempt_id: str = "1",
) -> Optional[Envelope]:
    """Emit the ``protocol_v1.Envelope`` for one ``TaskEnvelope`` transition.

    Returns ``None`` (emits nothing) when ``before`` and ``after`` are the
    same state, mirroring ``TaskEnvelope.transition``'s own idempotent
    no-op — a duplicated event never produces a duplicated lifecycle event
    either (AC: "repeating the same event does not duplicate state").
    """
    if before.task_id != after.task_id:
        raise ValueError(
            f"before/after task_id mismatch: {before.task_id!r} != {after.task_id!r}"
        )
    if before.state is after.state:
        if before != after:
            raise ValueError(
                "same-state transition changed envelope content; "
                "replay must be an exact no-op"
            )
        return None

    if not is_transition_allowed(before.state, after.state):
        raise InvalidTransitionError(before.state, after.state)

    for field_name in _LINEAGE_FIELDS:
        if getattr(before, field_name) != getattr(after, field_name):
            raise ValueError(f"before/after lineage mismatch for {field_name!r}")

    if after.updated_at_ns < before.updated_at_ns:
        raise ValueError("transition timestamp moved backwards")
    if before.worker is not None and after.worker is None:
        raise ValueError("worker cannot be removed by a transition")
    if before.lease is not None and after.lease is None:
        raise ValueError("lease cannot be removed by a transition")
    if (
        before.delivery_target is not None
        and after.delivery_target != before.delivery_target
    ):
        raise ValueError("delivery_target cannot be changed by a transition")
    expected_attempts = before.attempts + (after.state is TaskState.EXECUTING)
    if after.attempts != expected_attempts:
        raise ValueError(
            f"invalid attempt count for transition: {before.attempts} -> "
            f"{after.attempts}"
        )
    for field_name in ("artifacts", "receipts", "evidence_refs"):
        before_values = set(getattr(before, field_name))
        after_values = set(getattr(after, field_name))
        if not before_values.issubset(after_values):
            raise ValueError(f"{field_name} cannot be removed by a transition")
        before_order = getattr(before, field_name)
        after_order = getattr(after, field_name)
        if after_order[: len(before_order)] != before_order:
            raise ValueError(f"{field_name} must be append-only")

    event_type = STATE_TO_EVENT_TYPE[after.state]
    return emitter.emit(event_type, turn_id=turn_id, attempt_id=attempt_id)


__all__ = ["STATE_TO_EVENT_TYPE", "emit_for_transition"]
