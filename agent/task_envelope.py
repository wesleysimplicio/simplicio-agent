"""TaskEnvelope/v1 — a single versioned task lifecycle envelope + state machine.

Issue #209 (P0 architecture): every surface that can declare a task "done"
(the conversation loop, ``kernel_binding``, a runtime run, a workflow, the
simplicio-loop skill, session leases, GitHub/PR delivery, evidence capture)
today invents its own ad-hoc status string — see the issue-209 inventory:
``agent.conversation_loop`` free-form ``stored_state``/status strings,
``agent.distributed.protocol.TaskStatus`` (OK/ERROR/TIMEOUT/DENIED, an
*outcome* enum, not a lifecycle), ``tools.kanban_tools`` board statuses, and
``agent.verification_evidence.VerificationEvidence.status`` ("passed"/
"failed"). None of them agree, so no component can be trusted to say a task
is truly finished until the *whole* chain (orient -> plan -> claim -> execute
-> validate -> evidence -> deliver -> close) has actually run.

``TaskEnvelope`` is the single, versioned, schema-validated representation of
"where is this task right now" that every one of those surfaces should read
and write instead of a private status string. It intentionally mirrors the
conventions of :mod:`agent.protocol_v1` (immutable dataclass, ``to_dict`` /
``from_dict`` / ``to_json`` / ``from_json``, a pinned ``*_VERSION`` constant)
so the two envelopes compose rather than compete: a ``TaskEnvelope``
transition is expected to also emit a ``protocol_v1.Envelope`` lifecycle
event as its UI/audit-facing wire representation (the task envelope is the
durable *state*; the protocol envelope is the *event stream* about it).

State machine
-------------
Canonical (happy-path) states, in order::

    received -> oriented -> planned -> claimed -> executing -> validating
    -> evidence_ready -> delivered -> closed

Exception states, reachable from any non-terminal canonical state::

    blocked, cancelled, quarantined, failed

``blocked`` and ``failed`` may resume back into the canonical chain (a
blocked/failed task can be retried); ``cancelled`` and ``quarantined`` are
terminal, same as ``closed``. All transitions are looked up in
:data:`ALLOWED_TRANSITIONS`; anything not listed there raises
:class:`InvalidTransitionError` deterministically (AC: "Invalid transitions
are rejected deterministically"). Re-applying the *same* state is always a
no-op that returns an unchanged envelope rather than duplicating state or an
evidence/receipt entry (AC: "Repeating the same event does not duplicate
state or evidence").
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Optional

from agent._fastjson import dumps as _dumps, loads as _loads

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

TASK_ENVELOPE_SCHEMA = "simplicio.task-envelope"
TASK_ENVELOPE_SCHEMA_VERSION = "simplicio.task-envelope/v1"
"""Pinned schema id for :class:`TaskEnvelope`. Bump only on a breaking change."""


class TaskState(str, Enum):
    """Canonical + exception states for a task's lifecycle."""

    RECEIVED = "received"
    ORIENTED = "oriented"
    PLANNED = "planned"
    CLAIMED = "claimed"
    EXECUTING = "executing"
    VALIDATING = "validating"
    EVIDENCE_READY = "evidence_ready"
    DELIVERED = "delivered"
    CLOSED = "closed"

    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    QUARANTINED = "quarantined"
    FAILED = "failed"


#: Canonical happy-path order (used to build the forward-transition table).
CANONICAL_ORDER: tuple[TaskState, ...] = (
    TaskState.RECEIVED,
    TaskState.ORIENTED,
    TaskState.PLANNED,
    TaskState.CLAIMED,
    TaskState.EXECUTING,
    TaskState.VALIDATING,
    TaskState.EVIDENCE_READY,
    TaskState.DELIVERED,
    TaskState.CLOSED,
)

#: States that may still transition somewhere (non-terminal).
_NON_TERMINAL_CANONICAL = CANONICAL_ORDER[:-1]  # everything before CLOSED

#: Terminal states: no outgoing transitions at all (other than the no-op self-loop).
TERMINAL_STATES: FrozenSet[TaskState] = frozenset({
    TaskState.CLOSED,
    TaskState.CANCELLED,
    TaskState.QUARANTINED,
})


def _build_allowed_transitions() -> Dict[TaskState, FrozenSet[TaskState]]:
    table: Dict[TaskState, FrozenSet[TaskState]] = {}
    for i, state in enumerate(CANONICAL_ORDER):
        targets: set[TaskState] = set()
        if i + 1 < len(CANONICAL_ORDER):
            targets.add(CANONICAL_ORDER[i + 1])
        if state not in TERMINAL_STATES:
            targets.update({TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED})
            if state is not TaskState.RECEIVED:
                # quarantine requires having at least been oriented once.
                targets.add(TaskState.QUARANTINED)
        table[state] = frozenset(targets)

    # blocked/failed may resume back into the canonical chain (retry) or
    # escalate to a harder terminal state; they may not jump ahead.
    table[TaskState.BLOCKED] = frozenset(
        {TaskState.CANCELLED, TaskState.QUARANTINED} | set(_NON_TERMINAL_CANONICAL)
    )
    table[TaskState.FAILED] = frozenset(
        {TaskState.CANCELLED, TaskState.QUARANTINED} | set(_NON_TERMINAL_CANONICAL)
    )
    # terminal states have no outgoing transitions.
    table[TaskState.CANCELLED] = frozenset()
    table[TaskState.QUARANTINED] = frozenset()
    table[TaskState.CLOSED] = frozenset()
    return table


#: ``from_state -> {allowed to_states}``. A same-state transition is always
#: allowed (idempotent no-op) even though it is not listed explicitly here.
ALLOWED_TRANSITIONS: Dict[TaskState, FrozenSet[TaskState]] = (
    _build_allowed_transitions()
)


class InvalidTransitionError(ValueError):
    """Raised when a :class:`TaskEnvelope` transition is not allowed."""

    def __init__(self, from_state: TaskState, to_state: TaskState) -> None:
        allowed = sorted(
            s.value for s in ALLOWED_TRANSITIONS.get(from_state, frozenset())
        )
        super().__init__(
            f"invalid transition {from_state.value!r} -> {to_state.value!r}; "
            f"allowed from {from_state.value!r}: {allowed or '(terminal, none)'}"
        )
        self.from_state = from_state
        self.to_state = to_state


class CloseGateError(ValueError):
    """Raised when the strict ledger close gate cannot verify a task."""

    def __init__(self, decision: "CloseGateDecision") -> None:
        super().__init__(decision.reason)
        self.decision = decision


class CloseGateReason(str, Enum):
    """Typed reasons for strict close-gate decisions."""

    DELIVERED_REQUIRED = "delivered_required"
    EVIDENCE_REQUIRED = "evidence_required"
    VERIFIED_EVIDENCE_MISSING = "verified_evidence_missing"
    VERIFIED = "verified"


_CLOSE_GATE_REASON_TEXT: Dict[CloseGateReason, str] = {
    CloseGateReason.DELIVERED_REQUIRED: "close requires a delivered envelope",
    CloseGateReason.EVIDENCE_REQUIRED: "close requires at least one evidence reference",
    CloseGateReason.VERIFIED_EVIDENCE_MISSING: (
        "close requires every evidence reference to be verified"
    ),
    CloseGateReason.VERIFIED: "all required evidence references are verified",
}


@dataclass(frozen=True)
class CloseGateDecision:
    """Deterministic result of checking whether a task may be closed.

    ``TaskEnvelope.transition`` remains the compatibility-level state
    transition.  This stricter ledger boundary is opt-in for callers that
    need to distinguish a referenced receipt from a receipt independently
    verified by a watcher or test runner.
    """

    allowed: bool
    status: str
    reason_code: CloseGateReason
    reason: str
    required_evidence_refs: tuple[str, ...] = ()
    verified_evidence_refs: tuple[str, ...] = ()
    missing_evidence_refs: tuple[str, ...] = ()

    @property
    def quarantined(self) -> bool:
        return self.status == TaskState.QUARANTINED.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason_code": self.reason_code.value,
            "reason": self.reason,
            "required_evidence_refs": list(self.required_evidence_refs),
            "verified_evidence_refs": list(self.verified_evidence_refs),
            "missing_evidence_refs": list(self.missing_evidence_refs),
        }


def is_transition_allowed(from_state: TaskState, to_state: TaskState) -> bool:
    """True if ``to_state`` is reachable from ``from_state`` (or is a no-op)."""
    if from_state is to_state:
        return True
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskEnvelope:
    """Immutable, fully-populated task-lifecycle envelope.

    Construct via :meth:`TaskEnvelope.create` (fills ids/timestamps) or
    :meth:`TaskEnvelope.from_dict` (rebuild from a persisted/wire dict).
    Transition with :meth:`transition`, never by mutating fields directly —
    the dataclass is frozen specifically so every transition goes through
    validation.
    """

    schema: str
    schema_version: str

    task_id: str
    parent_id: Optional[str]
    correlation_id: str

    repo: str
    branch: str
    scope: str
    write_set: tuple[str, ...]

    acceptance_criteria: tuple[str, ...]

    risk_policy: str
    model: str
    execution_policy: str

    worker: Optional[str]
    lease: Optional[str]

    state: TaskState
    attempts: int
    created_at_ns: int
    updated_at_ns: int
    block_reason: Optional[str]

    artifacts: tuple[str, ...]
    receipts: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    delivery_target: Optional[str]

    def __post_init__(self) -> None:
        if self.schema != TASK_ENVELOPE_SCHEMA:
            raise ValueError(
                f"unsupported schema {self.schema!r}; expected {TASK_ENVELOPE_SCHEMA!r}"
            )
        if self.schema_version != TASK_ENVELOPE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r}; "
                f"expected {TASK_ENVELOPE_SCHEMA_VERSION!r}"
            )
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not isinstance(self.state, TaskState):
            raise ValueError(f"state must be a TaskState, got {self.state!r}")
        if not isinstance(self.created_at_ns, int) or self.created_at_ns < 0:
            raise ValueError(
                f"created_at_ns must be a non-negative integer, got {self.created_at_ns!r}"
            )
        if not isinstance(self.updated_at_ns, int) or self.updated_at_ns < 0:
            raise ValueError(
                f"updated_at_ns must be a non-negative integer, got {self.updated_at_ns!r}"
            )
        if self.updated_at_ns < self.created_at_ns:
            raise ValueError(
                "updated_at_ns must be greater than or equal to created_at_ns"
            )
        if not isinstance(self.attempts, int) or self.attempts < 0:
            raise ValueError(
                f"attempts must be a non-negative integer, got {self.attempts!r}"
            )
        for field_name in (
            "write_set",
            "acceptance_criteria",
            "artifacts",
            "receipts",
            "evidence_refs",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple):
                raise ValueError(f"{field_name} must be an immutable tuple")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
        if self.state is TaskState.BLOCKED and not (
            isinstance(self.block_reason, str) and self.block_reason.strip()
        ):
            raise ValueError("blocked envelopes require a non-empty block_reason")
        if self.state is not TaskState.BLOCKED and self.block_reason is not None:
            raise ValueError("block_reason is only valid for blocked envelopes")
        if self.state in (TaskState.CLOSED,) and not self.evidence_refs:
            raise ValueError(
                "cannot construct a CLOSED envelope with no evidence_refs "
                "(the system refuses `closed` without a valid evidence receipt)"
            )

    # -- construction --------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        repo: str,
        branch: str,
        scope: str,
        acceptance_criteria: List[str] | tuple[str, ...],
        risk_policy: str = "default",
        model: str = "",
        execution_policy: str = "default",
        write_set: List[str] | tuple[str, ...] = (),
        parent_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        task_id: Optional[str] = None,
        now_ns: Optional[int] = None,
    ) -> "TaskEnvelope":
        """Create a brand-new envelope in the ``received`` state."""
        ts = now_ns if now_ns is not None else time.time_ns()
        return cls(
            schema=TASK_ENVELOPE_SCHEMA,
            schema_version=TASK_ENVELOPE_SCHEMA_VERSION,
            task_id=task_id or uuid.uuid4().hex,
            parent_id=parent_id,
            correlation_id=correlation_id or uuid.uuid4().hex,
            repo=repo,
            branch=branch,
            scope=scope,
            write_set=tuple(write_set),
            acceptance_criteria=tuple(acceptance_criteria),
            risk_policy=risk_policy,
            model=model,
            execution_policy=execution_policy,
            worker=None,
            lease=None,
            state=TaskState.RECEIVED,
            attempts=0,
            created_at_ns=ts,
            updated_at_ns=ts,
            block_reason=None,
            artifacts=(),
            receipts=(),
            evidence_refs=(),
            delivery_target=None,
        )

    # -- transitions -----------------------------------------------------

    def transition(
        self,
        to_state: TaskState,
        *,
        worker: Optional[str] = None,
        lease: Optional[str] = None,
        block_reason: Optional[str] = None,
        artifacts: Optional[List[str] | tuple[str, ...]] = None,
        receipts: Optional[List[str] | tuple[str, ...]] = None,
        evidence_refs: Optional[List[str] | tuple[str, ...]] = None,
        delivery_target: Optional[str] = None,
        now_ns: Optional[int] = None,
    ) -> "TaskEnvelope":
        """Return a new envelope transitioned to ``to_state``.

        Raises :class:`InvalidTransitionError` if the transition is not in
        :data:`ALLOWED_TRANSITIONS`. Re-requesting the *current* state is an
        idempotent no-op: it returns ``self`` unchanged (same ``attempts``,
        same ``updated_at_ns``) so a duplicated event never double-counts an
        attempt or re-appends a receipt/evidence ref.
        """
        try:
            to_state = TaskState(to_state)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid state {to_state!r}") from exc
        if to_state is self.state:
            return self

        if not is_transition_allowed(self.state, to_state):
            raise InvalidTransitionError(self.state, to_state)

        ts = now_ns if now_ns is not None else time.time_ns()
        if ts < self.updated_at_ns:
            raise ValueError(
                "updated_at_ns must be greater than or equal to the prior value"
            )
        attempts = self.attempts
        if to_state is TaskState.EXECUTING:
            attempts = attempts + 1

        def _merge(
            existing: tuple[str, ...], new: Optional[List[str] | tuple[str, ...]]
        ) -> tuple[str, ...]:
            if not new:
                return existing
            if isinstance(new, str):
                raise ValueError("transition collections must be lists or tuples")
            merged = list(existing)
            for item in new:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("transition references must be non-empty strings")
                if item not in merged:
                    merged.append(item)
            return tuple(merged)

        return replace(
            self,
            worker=worker if worker is not None else self.worker,
            lease=lease if lease is not None else self.lease,
            state=to_state,
            attempts=attempts,
            updated_at_ns=ts,
            block_reason=block_reason if to_state is TaskState.BLOCKED else None,
            artifacts=_merge(self.artifacts, artifacts),
            receipts=_merge(self.receipts, receipts),
            evidence_refs=_merge(self.evidence_refs, evidence_refs),
            delivery_target=delivery_target
            if delivery_target is not None
            else self.delivery_target,
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    # -- ledger ------------------------------------------------------------

    def content_hash(self) -> str:
        """Stable sha256 hash of this envelope's content (for the ledger)."""
        payload = _dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def ledger_record(self) -> Dict[str, Any]:
        """A ``{task_id, envelope_hash, state, ...}`` record for the transition ledger."""
        return {
            "task_id": self.task_id,
            "envelope_hash": self.content_hash(),
            "state": self.state.value,
            "attempts": self.attempts,
            "updated_at_ns": self.updated_at_ns,
        }

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict with every field."""
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "parent_id": self.parent_id,
            "correlation_id": self.correlation_id,
            "repo": self.repo,
            "branch": self.branch,
            "scope": self.scope,
            "write_set": list(self.write_set),
            "acceptance_criteria": list(self.acceptance_criteria),
            "risk_policy": self.risk_policy,
            "model": self.model,
            "execution_policy": self.execution_policy,
            "worker": self.worker,
            "lease": self.lease,
            "state": self.state.value,
            "attempts": self.attempts,
            "created_at_ns": self.created_at_ns,
            "updated_at_ns": self.updated_at_ns,
            "block_reason": self.block_reason,
            "artifacts": list(self.artifacts),
            "receipts": list(self.receipts),
            "evidence_refs": list(self.evidence_refs),
            "delivery_target": self.delivery_target,
        }

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Serialize to a JSON string (stable, fastjson-backed)."""
        return _dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskEnvelope":
        """Rebuild an envelope from a dict; rejects an unknown ``state``."""
        try:
            raw_state = data["state"]
            try:
                state = TaskState(raw_state)
            except ValueError as exc:
                raise ValueError(f"invalid state {raw_state!r}") from exc
            return cls(
                schema=data["schema"],
                schema_version=data["schema_version"],
                task_id=data["task_id"],
                parent_id=data.get("parent_id"),
                correlation_id=data["correlation_id"],
                repo=data["repo"],
                branch=data["branch"],
                scope=data["scope"],
                write_set=tuple(data.get("write_set", ())),
                acceptance_criteria=tuple(data.get("acceptance_criteria", ())),
                risk_policy=data["risk_policy"],
                model=data["model"],
                execution_policy=data["execution_policy"],
                worker=data.get("worker"),
                lease=data.get("lease"),
                state=state,
                attempts=int(data["attempts"]),
                created_at_ns=int(data["created_at_ns"]),
                updated_at_ns=int(data["updated_at_ns"]),
                block_reason=data.get("block_reason"),
                artifacts=tuple(data.get("artifacts", ())),
                receipts=tuple(data.get("receipts", ())),
                evidence_refs=tuple(data.get("evidence_refs", ())),
                delivery_target=data.get("delivery_target"),
            )
        except KeyError as exc:
            raise ValueError(f"missing envelope field: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> "TaskEnvelope":
        """Rebuild an envelope from a JSON string."""
        return cls.from_dict(_loads(text))


class TaskLedger:
    """Append-only, in-process transition ledger keyed by ``task_id``.

    Persists ``{task_id, envelope_hash, state, ...}`` for every transition
    (AC: "Persist every transition to a ledger with task_id + envelope
    hash"). This is an in-memory reference implementation; a durable backend
    (SQLite/file) can wrap the same ``append``/``history`` contract.
    """

    def __init__(self) -> None:
        self._records: Dict[str, List[Dict[str, Any]]] = {}
        self._quarantine_records: Dict[str, List[Dict[str, Any]]] = {}

    @staticmethod
    def _quarantine_record_key(record: Dict[str, Any]) -> tuple[Any, ...]:
        return (
            record.get("task_id"),
            record.get("envelope_hash"),
            record.get("reason_code"),
            tuple(record.get("required_evidence_refs", ()) or ()),
            tuple(record.get("verified_evidence_refs", ()) or ()),
            tuple(record.get("missing_evidence_refs", ()) or ()),
        )

    def append(self, envelope: TaskEnvelope) -> Dict[str, Any]:
        record = envelope.ledger_record()
        history = self._records.setdefault(envelope.task_id, [])
        if history and history[-1]["envelope_hash"] == record["envelope_hash"]:
            # idempotent: the same envelope content was already recorded.
            return history[-1]
        history.append(record)
        return record

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot for recovery/replay."""
        return {
            "records": {
                task_id: [dict(record) for record in history]
                for task_id, history in self._records.items()
            },
            "quarantine_records": {
                task_id: [dict(record) for record in history]
                for task_id, history in self._quarantine_records.items()
            },
        }

    def replay_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Merge a prior snapshot back into this ledger idempotently."""
        for task_id, history in snapshot.get("records", {}).items():
            current = self._records.setdefault(task_id, [])
            seen_hashes = {record["envelope_hash"] for record in current}
            for record in history:
                envelope_hash = record.get("envelope_hash")
                if not envelope_hash or envelope_hash in seen_hashes:
                    continue
                current.append(dict(record))
                seen_hashes.add(envelope_hash)

        for task_id, history in snapshot.get("quarantine_records", {}).items():
            current = self._quarantine_records.setdefault(task_id, [])
            seen_keys = {self._quarantine_record_key(record) for record in current}
            for record in history:
                key = self._quarantine_record_key(record)
                if key in seen_keys:
                    continue
                current.append(dict(record))
                seen_keys.add(key)

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> "TaskLedger":
        """Rebuild a ledger snapshot without duplicating replayed records."""
        ledger = cls()
        ledger.replay_snapshot(snapshot)
        return ledger

    def history(self, task_id: str) -> tuple[Dict[str, Any], ...]:
        return tuple(self._records.get(task_id, ()))

    @staticmethod
    def evaluate_close_gate(
        envelope: TaskEnvelope,
        *,
        verified_evidence_refs: Iterable[str] = (),
    ) -> CloseGateDecision:
        """Check close eligibility without trusting receipt names alone.

        The caller supplies references produced by an independent verifier.
        Ordering of that input is intentionally ignored; the envelope's
        evidence order is the canonical order used in the decision.
        """
        required = tuple(dict.fromkeys(envelope.evidence_refs))
        verified = set(verified_evidence_refs)
        observed = tuple(ref for ref in required if ref in verified)
        missing = tuple(ref for ref in required if ref not in verified)

        if envelope.state not in {TaskState.DELIVERED, TaskState.CLOSED}:
            return CloseGateDecision(
                allowed=False,
                status=TaskState.QUARANTINED.value,
                reason_code=CloseGateReason.DELIVERED_REQUIRED,
                reason=_CLOSE_GATE_REASON_TEXT[CloseGateReason.DELIVERED_REQUIRED],
                required_evidence_refs=required,
                verified_evidence_refs=observed,
                missing_evidence_refs=missing,
            )
        if not required:
            return CloseGateDecision(
                allowed=False,
                status=TaskState.QUARANTINED.value,
                reason_code=CloseGateReason.EVIDENCE_REQUIRED,
                reason=_CLOSE_GATE_REASON_TEXT[CloseGateReason.EVIDENCE_REQUIRED],
                required_evidence_refs=required,
                verified_evidence_refs=observed,
                missing_evidence_refs=missing,
            )
        if missing:
            return CloseGateDecision(
                allowed=False,
                status=TaskState.QUARANTINED.value,
                reason_code=CloseGateReason.VERIFIED_EVIDENCE_MISSING,
                reason=_CLOSE_GATE_REASON_TEXT[
                    CloseGateReason.VERIFIED_EVIDENCE_MISSING
                ],
                required_evidence_refs=required,
                verified_evidence_refs=observed,
                missing_evidence_refs=missing,
            )
        return CloseGateDecision(
            allowed=True,
            status=TaskState.CLOSED.value,
            reason_code=CloseGateReason.VERIFIED,
            reason=_CLOSE_GATE_REASON_TEXT[CloseGateReason.VERIFIED],
            required_evidence_refs=required,
            verified_evidence_refs=observed,
        )

    def _record_quarantine(
        self, envelope: TaskEnvelope, decision: CloseGateDecision
    ) -> Dict[str, Any]:
        record = {
            "task_id": envelope.task_id,
            "envelope_hash": envelope.content_hash(),
            "state": TaskState.QUARANTINED.value,
            "reason_code": decision.reason_code.value,
            "reason": decision.reason,
            "required_evidence_refs": list(decision.required_evidence_refs),
            "verified_evidence_refs": list(decision.verified_evidence_refs),
            "missing_evidence_refs": list(decision.missing_evidence_refs),
        }
        history = self._quarantine_records.setdefault(envelope.task_id, [])
        key = self._quarantine_record_key(record)
        for existing in history:
            if self._quarantine_record_key(existing) == key:
                return existing
        history.append(record)
        return record

    def quarantine_history(self, task_id: str) -> tuple[Dict[str, Any], ...]:
        """Return close-gate quarantine records for ``task_id``."""
        return tuple(self._quarantine_records.get(task_id, ()))

    def close_if_verified(
        self,
        envelope: TaskEnvelope,
        *,
        verified_evidence_refs: Iterable[str] = (),
    ) -> TaskEnvelope:
        """Close and ledger-record an envelope only after explicit proof.

        A denied attempt is retained in the quarantine ledger, but the
        immutable envelope is not mutated or silently promoted to closed.
        """
        decision = self.evaluate_close_gate(
            envelope, verified_evidence_refs=verified_evidence_refs
        )
        if not decision.allowed:
            self._record_quarantine(envelope, decision)
            raise CloseGateError(decision)
        closed = (
            envelope
            if envelope.state is TaskState.CLOSED
            else envelope.transition(TaskState.CLOSED)
        )
        self.append(closed)
        return closed


__all__ = [
    "TASK_ENVELOPE_SCHEMA",
    "TASK_ENVELOPE_SCHEMA_VERSION",
    "TaskState",
    "CANONICAL_ORDER",
    "TERMINAL_STATES",
    "ALLOWED_TRANSITIONS",
    "InvalidTransitionError",
    "CloseGateError",
    "CloseGateReason",
    "CloseGateDecision",
    "is_transition_allowed",
    "TaskEnvelope",
    "TaskLedger",
]
