"""AgentProtocol/v1 — a versioned, causal event envelope.

This module is the single source of truth for the *shape* of events that
travel across every Simplicio Agent surface (CLI, gateway, TUI, desktop,
ACP). It deliberately does **not** touch any surface: it only defines the
typed :class:`Envelope` and an :class:`Emitter` helper that producers use to
stamp events with causal metadata (session / turn / attempt / monotonic seq).

Why a typed envelope instead of ad-hoc dicts?
---------------------------------------------
Previously the same causal fields (``session_id``, ``turn_id``, ``seq``...)
were re-invented at every call site and never consistently present. A
shared envelope means:

* every consumer can rely on the full field set being populated,
* ``seq`` is monotonic *per* ``turn_id`` (causal ordering within a turn),
* an invalid ``event_type`` is rejected at construction time, not at
  consume time,
* a single serialization format (fastjson, mirroring the hot paths in
  :mod:`agent.conversation_loop`) is used everywhere.

Field semantics
---------------
* ``protocol_version`` — pinned to ``"agent/v1"``. Bump only on a breaking
  wire change.
* ``event_id`` — globally unique id for this envelope (UUID4 hex).
* ``session_id`` — conversation/session the event belongs to.
* ``session_incarnation`` — monotonic counter incremented whenever a session
  is reset/reborn (``/new``, reconnect-forcing reset). Lets consumers drop
  stale events from a previous incarnation.
* ``turn_id`` — the user turn this event belongs to. ``seq`` is monotonic
  *within* a ``turn_id``.
* ``attempt_id`` — a retry/attempt within a turn (a turn may be retried on
  provider failure). Events sharing a ``turn_id`` but differing
  ``attempt_id`` belong to distinct executions of that turn.
* ``seq`` — positive, monotonically increasing integer scoped to
  ``turn_id``. ``1`` is the first event of a turn.
* ``ts_monotonic_ns`` — ``time.monotonic_ns()``; only useful for
  *relative* ordering, never wall-clock comparison.
* ``ts_wall_ns`` — ``time.time_ns()``; wall-clock for human-visible logs /
  span boundaries.
* ``event_type`` — dotted string resolved from one of the :class:`LifecycleEvent`,
  :class:`PresentationEvent`, :class:`ExecutionEvent`, :class:`ControlCommand`
  families. An unknown value is rejected (see test c).
* ``payload_version`` — schema version of ``payload`` carried by the consumer
  (independent of ``protocol_version``).
* ``redaction_class`` — redaction bucket for the payload (``none``,
  ``secret``, ``pii``, ``tool_io`` ...). Mirrors :mod:`agent.redact` intent.
* ``trace_id`` — distributed-trace id tying this event to a request tree.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, Iterable, Mapping, Optional

from agent._fastjson import dumps as _dumps, loads as _loads

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "agent/v1"
"""Wire protocol version for AgentProtocol/v1 envelopes."""

PAYLOAD_VERSION = "1.0"
"""Default payload schema version attached by :class:`Emitter`."""

# Default redaction bucket for payloads that need no masking.
REDACTION_NONE = "none"
REDACTION_SECRET = "secret"

EXECUTION_CONTEXT_SCHEMA = "simplicio.execution-context/v1"
RUN_EVENT_SCHEMA = "simplicio.run-event/v1"

_SECRET_REDACTION_TOKEN = "[redacted]"
_RUN_CONTEXT_MUTABLE_FIELDS = frozenset(
    {
        "phase",
        "step",
        "budgets",
        "checkpoint_ref",
        "effect_journal_ref",
        "ledger_ref",
        "evidence_coverage",
    }
)


# ---------------------------------------------------------------------------
# Event-type families
# ---------------------------------------------------------------------------


class LifecycleEvent(str, Enum):
    """Agent lifecycle transitions for a turn/session."""

    ACCEPTED = "lifecycle.accepted"
    STARTED = "lifecycle.started"
    PAUSED = "lifecycle.paused"
    RESUMED = "lifecycle.resumed"
    CANCELLED = "lifecycle.cancelled"
    COMPLETED = "lifecycle.completed"
    FAILED = "lifecycle.failed"


class PresentationEvent(str, Enum):
    """Things the user perceives (text, reasoning, progress)."""

    TEXT = "presentation.text"
    REASONING = "presentation.reasoning"
    PROGRESS = "presentation.progress"


class ExecutionEvent(str, Enum):
    """Backend execution telemetry (provider, tools, approvals, checkpoints)."""

    PROVIDER = "execution.provider"
    TOOL = "execution.tool"
    APPROVAL = "execution.approval"
    CHECKPOINT = "execution.checkpoint"


class ControlCommand(str, Enum):
    """Commands flowing *into* the agent (control plane)."""

    START = "control.start"
    CANCEL = "control.cancel"
    RESUME = "control.resume"
    APPROVAL = "control.approval"
    RECONNECT = "control.reconnect"


# The four families, in the order surfaces typically dispatch them.
EVENT_FAMILIES = (LifecycleEvent, PresentationEvent, ExecutionEvent, ControlCommand)

#: Frozen set of every valid ``event_type`` string across all families.
VALID_EVENT_TYPES: frozenset[str] = frozenset(
    member.value for family in EVENT_FAMILIES for member in family
)


def _event_family_of(event_type: str) -> Optional[type]:
    """Return the enum family an ``event_type`` belongs to, or ``None``."""
    for family in EVENT_FAMILIES:
        if event_type in {m.value for m in family}:
            return family
    return None


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Envelope:
    """Immutable, fully-populated causal event envelope.

    Construct directly only when you already have every field (e.g. when
    rebuilding from a serialized dict). Producers should prefer
    :meth:`Envelope.create` or the :class:`Emitter` helper, which stamp the
    ids/seq/timestamps for you.
    """

    protocol_version: str
    event_id: str
    session_id: str
    session_incarnation: int
    turn_id: str
    attempt_id: str
    seq: int
    ts_monotonic_ns: int
    ts_wall_ns: int
    event_type: str
    payload_version: str
    redaction_class: str
    trace_id: str

    def __post_init__(self) -> None:
        if self.event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"invalid event_type {self.event_type!r}; "
                f"expected one of {sorted(VALID_EVENT_TYPES)}"
            )
        if self.seq <= 0:
            raise ValueError(f"seq must be a positive integer, got {self.seq!r}")
        if self.session_incarnation < 0:
            raise ValueError(
                f"session_incarnation must be >= 0, got {self.session_incarnation!r}"
            )

    # -- construction ------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        session_id: str,
        turn_id: str,
        attempt_id: str,
        seq: int,
        session_incarnation: int = 0,
        payload_version: str = PAYLOAD_VERSION,
        redaction_class: str = REDACTION_NONE,
        trace_id: str = "",
        protocol_version: str = PROTOCOL_VERSION,
        event_id: Optional[str] = None,
        ts_monotonic_ns: Optional[int] = None,
        ts_wall_ns: Optional[int] = None,
    ) -> "Envelope":
        """Build an envelope, filling ids/timestamps when omitted."""
        return cls(
            protocol_version=protocol_version,
            event_id=event_id or uuid.uuid4().hex,
            session_id=session_id,
            session_incarnation=session_incarnation,
            turn_id=turn_id,
            attempt_id=attempt_id,
            seq=seq,
            ts_monotonic_ns=ts_monotonic_ns
            if ts_monotonic_ns is not None
            else time.monotonic_ns(),
            ts_wall_ns=ts_wall_ns if ts_wall_ns is not None else time.time_ns(),
            event_type=event_type,
            payload_version=payload_version,
            redaction_class=redaction_class,
            trace_id=trace_id or uuid.uuid4().hex,
        )

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict with every field."""
        return {
            "protocol_version": self.protocol_version,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "session_incarnation": self.session_incarnation,
            "turn_id": self.turn_id,
            "attempt_id": self.attempt_id,
            "seq": self.seq,
            "ts_monotonic_ns": self.ts_monotonic_ns,
            "ts_wall_ns": self.ts_wall_ns,
            "event_type": self.event_type,
            "payload_version": self.payload_version,
            "redaction_class": self.redaction_class,
            "trace_id": self.trace_id,
        }

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Serialize to a JSON string (stable, fastjson-backed)."""
        return _dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Envelope":
        """Rebuild an envelope from a dict; rejects unknown ``event_type``."""
        try:
            return cls(
                protocol_version=data["protocol_version"],
                event_id=data["event_id"],
                session_id=data["session_id"],
                session_incarnation=int(data["session_incarnation"]),
                turn_id=data["turn_id"],
                attempt_id=data["attempt_id"],
                seq=int(data["seq"]),
                ts_monotonic_ns=int(data["ts_monotonic_ns"]),
                ts_wall_ns=int(data["ts_wall_ns"]),
                event_type=data["event_type"],
                payload_version=data["payload_version"],
                redaction_class=data["redaction_class"],
                trace_id=data["trace_id"],
            )
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"missing envelope field: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> "Envelope":
        """Rebuild an envelope from a JSON string."""
        return cls.from_dict(_loads(text))

    # -- convenience -------------------------------------------------------

    @property
    def event_family(self) -> Optional[type]:
        """The enum family this ``event_type`` belongs to, or ``None``."""
        return _event_family_of(self.event_type)


class DuplicateEventError(ValueError):
    """Raised when one event id is reused for different envelope content."""

    def __init__(self, event_id: str) -> None:
        super().__init__(
            f"event_id {event_id!r} was replayed with different envelope content"
        )
        self.event_id = event_id


class EventDeduplicator:
    """Accept each ``Envelope.event_id`` once during an event-log replay.

    Exact repeats are ignored. Reusing an id for different content is rejected
    rather than silently dropping a potentially corrupted or ambiguous event.
    ``replay`` validates the complete batch before committing new ids, so a
    collision cannot leave a partially accepted batch behind.
    """

    def __init__(self) -> None:
        self._events: Dict[str, Envelope] = {}

    def accept(self, event: Envelope) -> bool:
        """Record one event and return whether it is new."""
        previous = self._events.get(event.event_id)
        if previous is None:
            self._events[event.event_id] = event
            return True
        if previous != event:
            raise DuplicateEventError(event.event_id)
        return False

    def replay(self, events: Iterable[Envelope]) -> tuple[Envelope, ...]:
        """Return first-seen events in input order, suppressing exact repeats."""
        pending: Dict[str, Envelope] = {}
        accepted: list[Envelope] = []
        for event in events:
            previous = pending.get(event.event_id)
            if previous is None:
                previous = self._events.get(event.event_id)
            if previous is None:
                pending[event.event_id] = event
                accepted.append(event)
            elif previous != event:
                raise DuplicateEventError(event.event_id)
        self._events.update(pending)
        return tuple(accepted)

    def __len__(self) -> int:
        """Return the number of distinct event ids accepted so far."""
        return len(self._events)


def _freeze_json(value: Any) -> Any:
    """Recursively normalize values into deterministic JSON-compatible shapes."""
    if isinstance(value, tuple):
        return [_freeze_json(item) for item in value]
    if isinstance(value, list):
        return [_freeze_json(item) for item in value]
    if isinstance(value, set):
        frozen = [_freeze_json(item) for item in value]
        return sorted(frozen, key=lambda item: _dumps(item, ensure_ascii=False))
    if isinstance(value, Mapping):
        return {key: _freeze_json(value[key]) for key in sorted(value)}
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    return _dumps(_freeze_json(value), ensure_ascii=False).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_tuple(values: Iterable[str]) -> tuple[str, ...]:
    items = tuple(value for value in values if value)
    return tuple(sorted(items))


def _canonical_budgets(value: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: _freeze_json(value[key]) for key in sorted(value)
    }


def _redact_payload(
    payload: Any,
    *,
    redaction_class: str,
    secret_paths: frozenset[str],
    path: str = "",
) -> Any:
    if redaction_class == REDACTION_SECRET and path:
        return _SECRET_REDACTION_TOKEN
    if path in secret_paths:
        return _SECRET_REDACTION_TOKEN
    if isinstance(payload, Mapping):
        return {
            key: _redact_payload(
                payload[key],
                redaction_class=redaction_class,
                secret_paths=secret_paths,
                path=f"{path}.{key}" if path else str(key),
            )
            for key in sorted(payload)
        }
    if isinstance(payload, list):
        return [
            _redact_payload(
                item,
                redaction_class=redaction_class,
                secret_paths=secret_paths,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(payload)
        ]
    if isinstance(payload, tuple):
        return [
            _redact_payload(
                item,
                redaction_class=redaction_class,
                secret_paths=secret_paths,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(payload)
        ]
    return payload


class EventClassification(str, Enum):
    """Confidence class attached to a run event payload/effect."""

    MEASURED = "MEASURED"
    CANON = "CANON"
    INFERRED = "INFERRED"
    PLANNED = "PLANNED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SecretSafePayload:
    """Serializable payload record that never emits raw secret material."""

    payload_ref: str
    redaction_class: str = REDACTION_NONE
    payload: Any = None
    secret_paths: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.payload_ref:
            raise ValueError("payload_ref must be non-empty")

    @classmethod
    def inline(
        cls,
        payload: Any,
        *,
        redaction_class: str = REDACTION_NONE,
        payload_ref: Optional[str] = None,
        secret_paths: Iterable[str] = (),
    ) -> "SecretSafePayload":
        frozen_paths = frozenset(secret_paths)
        redacted = _redact_payload(
            payload,
            redaction_class=redaction_class,
            secret_paths=frozen_paths,
        )
        canonical = _freeze_json(redacted)
        return cls(
            payload_ref=payload_ref or f"inline:{_canonical_hash(canonical)}",
            redaction_class=redaction_class,
            payload=canonical,
            secret_paths=tuple(sorted(frozen_paths)),
        )

    @classmethod
    def handle(
        cls,
        payload_ref: str,
        *,
        preview: Any = None,
        redaction_class: str = REDACTION_SECRET,
    ) -> "SecretSafePayload":
        preview_payload = None
        if preview is not None:
            preview_payload = _redact_payload(
                preview,
                redaction_class=redaction_class,
                secret_paths=frozenset(),
            )
        return cls(
            payload_ref=payload_ref,
            redaction_class=redaction_class,
            payload=_freeze_json(preview_payload),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload_ref": self.payload_ref,
            "redaction_class": self.redaction_class,
            "payload": _freeze_json(self.payload),
            "secret_paths": list(self.secret_paths),
        }

    def canonical_hash(self) -> str:
        return _canonical_hash(self.to_dict())


@dataclass(frozen=True)
class ExecutionContext:
    """Canonical execution authority shared across producers and replayers."""

    profile_id: str
    tenant_id: str
    session_id: str
    run_id: str
    parent_run_id: str = ""
    goal_hash: str = ""
    anchor_hash: str = ""
    phase: str = ""
    step: str = ""
    budgets: Dict[str, Any] = field(default_factory=dict)
    policy_ref: str = ""
    capability_refs: tuple[str, ...] = field(default_factory=tuple)
    checkpoint_ref: str = ""
    effect_journal_ref: str = ""
    ledger_ref: str = ""
    evidence_coverage: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = EXECUTION_CONTEXT_SCHEMA

    def __post_init__(self) -> None:
        for field_name in ("profile_id", "tenant_id", "session_id", "run_id"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must be non-empty")
        object.__setattr__(self, "budgets", _canonical_budgets(self.budgets))
        object.__setattr__(
            self, "capability_refs", _canonical_tuple(self.capability_refs)
        )
        object.__setattr__(
            self, "evidence_coverage", _canonical_tuple(self.evidence_coverage)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "goal_hash": self.goal_hash,
            "anchor_hash": self.anchor_hash,
            "phase": self.phase,
            "step": self.step,
            "budgets": _freeze_json(self.budgets),
            "policy_ref": self.policy_ref,
            "capability_refs": list(self.capability_refs),
            "checkpoint_ref": self.checkpoint_ref,
            "effect_journal_ref": self.effect_journal_ref,
            "ledger_ref": self.ledger_ref,
            "evidence_coverage": list(self.evidence_coverage),
        }

    def canonical_hash(self) -> str:
        return _canonical_hash(self.to_dict())

    def stable_projection(self) -> Dict[str, Any]:
        data = self.to_dict()
        for field_name in _RUN_CONTEXT_MUTABLE_FIELDS:
            data.pop(field_name, None)
        return data


@dataclass(frozen=True)
class ReplayCursor:
    """Stable reconnect cursor for a confirmed point in one run stream."""

    run_id: str
    sequence: int
    event_id: str

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be non-empty")
        if self.sequence < 0:
            raise ValueError(f"sequence must be >= 0, got {self.sequence!r}")
        if self.sequence and not self.event_id:
            raise ValueError("event_id must be non-empty when sequence > 0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_id": self.event_id,
        }


@dataclass(frozen=True)
class RunEvent:
    """Execution-context-aware event record layered over :class:`Envelope`."""

    envelope: Envelope
    context: ExecutionContext
    actor: str
    source: str
    classification: str = EventClassification.UNKNOWN.value
    causal_parent: str = ""
    idempotency_key: str = ""
    payload: SecretSafePayload = field(
        default_factory=lambda: SecretSafePayload.handle("payload:none", preview={})
    )
    receipt_hash: str = ""
    observed_at_ns: int = 0
    valid_at_ns: int = 0
    schema_version: str = RUN_EVENT_SCHEMA

    def __post_init__(self) -> None:
        if self.envelope.session_id != self.context.session_id:
            raise ValueError("envelope.session_id must match context.session_id")
        if self.context.run_id == "":
            raise ValueError("context.run_id must be non-empty")
        if not self.actor:
            raise ValueError("actor must be non-empty")
        if not self.source:
            raise ValueError("source must be non-empty")
        if self.classification not in {member.value for member in EventClassification}:
            raise ValueError(f"invalid classification {self.classification!r}")
        observed = self.observed_at_ns or self.envelope.ts_monotonic_ns
        valid = self.valid_at_ns or self.envelope.ts_wall_ns
        object.__setattr__(self, "observed_at_ns", observed)
        object.__setattr__(self, "valid_at_ns", valid)
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", self._default_idempotency_key())

    @property
    def event_id(self) -> str:
        return self.envelope.event_id

    @property
    def run_id(self) -> str:
        return self.context.run_id

    @property
    def sequence(self) -> int:
        return self.envelope.seq

    @property
    def event_type(self) -> str:
        return self.envelope.event_type

    def _default_idempotency_key(self) -> str:
        return _canonical_hash(
            {
                "run_id": self.context.run_id,
                "causal_parent": self.causal_parent,
                "event_type": self.envelope.event_type,
                "actor": self.actor,
                "source": self.source,
                "payload_ref": self.payload.payload_ref,
                "receipt_hash": self.receipt_hash,
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "causal_parent": self.causal_parent,
            "sequence": self.sequence,
            "idempotency_key": self.idempotency_key,
            "type": self.event_type,
            "actor": self.actor,
            "source": self.source,
            "observed_at_ns": self.observed_at_ns,
            "valid_at_ns": self.valid_at_ns,
            "payload": self.payload.to_dict(),
            "classification": self.classification,
            "receipt_hash": self.receipt_hash,
            "envelope": self.envelope.to_dict(),
            "context": self.context.to_dict(),
        }

    def canonical_hash(self) -> str:
        return _canonical_hash(self.to_dict())


class SequenceGapError(ValueError):
    """Raised when replay/append skips a required run-local sequence number."""

    def __init__(self, run_id: str, expected: int, got: int) -> None:
        super().__init__(
            f"run_id {run_id!r} expected sequence {expected}, got {got}"
        )
        self.run_id = run_id
        self.expected = expected
        self.got = got


class IdempotencyConflictError(ValueError):
    """Raised when one idempotency key is reused for different events."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"idempotency_key {key!r} was reused for different event content"
        )
        self.key = key


class ImmutableContextError(ValueError):
    """Raised when a producer mutates immutable run authority state."""

    def __init__(self, field_name: str, source: str) -> None:
        super().__init__(
            f"{source!r} event attempted to mutate immutable context field {field_name!r}"
        )
        self.field_name = field_name
        self.source = source


@dataclass(frozen=True)
class ReplayProjection:
    """Deterministic state snapshot materialized from a run-event replay."""

    run_id: str
    phase: str
    step: str
    status: str
    last_sequence: int
    last_event_id: str
    event_count: int
    cursor: ReplayCursor
    classification_counts: Dict[str, int]
    event_type_counts: Dict[str, int]
    effect_receipts: tuple[str, ...]
    context: ExecutionContext

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "step": self.step,
            "status": self.status,
            "last_sequence": self.last_sequence,
            "last_event_id": self.last_event_id,
            "event_count": self.event_count,
            "cursor": self.cursor.to_dict(),
            "classification_counts": _freeze_json(self.classification_counts),
            "event_type_counts": _freeze_json(self.event_type_counts),
            "effect_receipts": list(self.effect_receipts),
            "context": self.context.to_dict(),
        }

    def canonical_hash(self) -> str:
        return _canonical_hash(self.to_dict())


class RunEventStream:
    """Append-only, bounded run stream with replay projection and dedupe."""

    def __init__(self, *, context: ExecutionContext) -> None:
        self._context = context
        self._events: list[RunEvent] = []
        self._events_by_id: Dict[str, RunEvent] = {}
        self._events_by_idempotency: Dict[str, RunEvent] = {}

    @property
    def context(self) -> ExecutionContext:
        return self._context

    def append(self, event: RunEvent) -> bool:
        self._validate_event(event)
        previous = self._events_by_id.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise DuplicateEventError(event.event_id)
            return False
        previous_by_key = self._events_by_idempotency.get(event.idempotency_key)
        if previous_by_key is not None:
            if previous_by_key != event:
                raise IdempotencyConflictError(event.idempotency_key)
            return False
        expected = len(self._events) + 1
        if event.sequence != expected:
            raise SequenceGapError(event.run_id, expected, event.sequence)
        self._events.append(event)
        self._events_by_id[event.event_id] = event
        self._events_by_idempotency[event.idempotency_key] = event
        return True

    def replay(self, events: Iterable[RunEvent]) -> tuple[RunEvent, ...]:
        accepted: list[RunEvent] = []
        snapshot = RunEventStream(context=self._context)
        for event in self._events:
            snapshot.append(event)
        for event in events:
            if snapshot.append(event):
                accepted.append(event)
        self._events = snapshot._events
        self._events_by_id = snapshot._events_by_id
        self._events_by_idempotency = snapshot._events_by_idempotency
        return tuple(accepted)

    def project(self) -> ReplayProjection:
        last = self._events[-1] if self._events else None
        phase = last.context.phase if last is not None else self._context.phase
        step = last.context.step if last is not None else self._context.step
        status = "idle"
        classification_counts: Dict[str, int] = {}
        event_type_counts: Dict[str, int] = {}
        effect_receipts: list[str] = []
        lifecycle_to_status = {
            LifecycleEvent.ACCEPTED.value: "accepted",
            LifecycleEvent.STARTED.value: "running",
            LifecycleEvent.PAUSED.value: "paused",
            LifecycleEvent.RESUMED.value: "running",
            LifecycleEvent.CANCELLED.value: "cancelled",
            LifecycleEvent.COMPLETED.value: "completed",
            LifecycleEvent.FAILED.value: "failed",
        }
        for event in self._events:
            classification_counts[event.classification] = (
                classification_counts.get(event.classification, 0) + 1
            )
            event_type_counts[event.event_type] = (
                event_type_counts.get(event.event_type, 0) + 1
            )
            if event.receipt_hash and event.receipt_hash not in effect_receipts:
                effect_receipts.append(event.receipt_hash)
            status = lifecycle_to_status.get(event.event_type, status)
        last_sequence = last.sequence if last is not None else 0
        last_event_id = last.event_id if last is not None else ""
        return ReplayProjection(
            run_id=self._context.run_id,
            phase=phase,
            step=step,
            status=status,
            last_sequence=last_sequence,
            last_event_id=last_event_id,
            event_count=len(self._events),
            cursor=ReplayCursor(
                run_id=self._context.run_id,
                sequence=last_sequence,
                event_id=last_event_id,
            ),
            classification_counts=classification_counts,
            event_type_counts=event_type_counts,
            effect_receipts=tuple(effect_receipts),
            context=last.context if last is not None else self._context,
        )

    def events_after(self, cursor: ReplayCursor) -> tuple[RunEvent, ...]:
        if cursor.run_id != self._context.run_id:
            raise ValueError("cursor.run_id must match stream run_id")
        if cursor.sequence == 0:
            return tuple(self._events)
        if cursor.sequence > len(self._events):
            raise SequenceGapError(cursor.run_id, len(self._events), cursor.sequence)
        current = self._events[cursor.sequence - 1]
        if current.event_id != cursor.event_id:
            raise DuplicateEventError(cursor.event_id)
        return tuple(self._events[cursor.sequence :])

    def _validate_event(self, event: RunEvent) -> None:
        if event.run_id != self._context.run_id:
            raise ValueError("event.run_id must match stream context.run_id")
        if event.context.session_id != self._context.session_id:
            raise ValueError("event.session_id must match stream context.session_id")
        for field_name, expected in self._context.stable_projection().items():
            got = event.context.stable_projection().get(field_name)
            if got != expected:
                raise ImmutableContextError(field_name, event.source)
        if event.source in {"tool", "provider"}:
            for field_name in ("goal_hash", "anchor_hash"):
                if getattr(event.context, field_name) != getattr(self._context, field_name):
                    raise ImmutableContextError(field_name, event.source)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterable[RunEvent]:
        return iter(self._events)


# ---------------------------------------------------------------------------
# Emitter helper
# ---------------------------------------------------------------------------


class Emitter:
    """Stamp causal metadata onto envelopes for a single session.

    The emitter owns the per-``turn_id`` monotonic ``seq`` counter (and the
    ``session_incarnation`` counter), so producers never have to track them
    by hand. It is safe to share one emitter across threads — the ``seq``
    bookkeeping is guarded by a lock.
    """

    def __init__(
        self,
        session_id: str,
        *,
        trace_id: Optional[str] = None,
        payload_version: str = PAYLOAD_VERSION,
        session_incarnation: int = 0,
    ) -> None:
        self.session_id = session_id
        self.trace_id = trace_id or uuid.uuid4().hex
        self.payload_version = payload_version
        self._session_incarnation = session_incarnation
        self._seq: Dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def session_incarnation(self) -> int:
        return self._session_incarnation

    def next_seq(self, turn_id: str) -> int:
        """Return the next monotonic ``seq`` for ``turn_id`` (thread-safe)."""
        with self._lock:
            nxt = self._seq.get(turn_id, 0) + 1
            self._seq[turn_id] = nxt
            return nxt

    def reset_turn(self, turn_id: str) -> None:
        """Restart ``seq`` numbering for ``turn_id`` (e.g. a brand-new turn)."""
        with self._lock:
            self._seq[turn_id] = 0

    def incarnate(self) -> int:
        """Bump the session incarnation and return the new value."""
        with self._lock:
            self._session_incarnation += 1
            return self._session_incarnation

    def emit(
        self,
        event_type: str,
        *,
        turn_id: str,
        attempt_id: str,
        redaction_class: str = REDACTION_NONE,
        payload_version: Optional[str] = None,
        trace_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> Envelope:
        """Emit one envelope with freshly stamped causal metadata.

        ``event_type`` is validated against :data:`VALID_EVENT_TYPES`; an
        invalid value raises :class:`ValueError` before any stamping.
        """
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"invalid event_type {event_type!r}; "
                f"expected one of {sorted(VALID_EVENT_TYPES)}"
            )
        seq = self.next_seq(turn_id)
        return Envelope.create(
            event_type=event_type,
            session_id=self.session_id,
            session_incarnation=self._session_incarnation,
            turn_id=turn_id,
            attempt_id=attempt_id,
            seq=seq,
            payload_version=payload_version or self.payload_version,
            redaction_class=redaction_class,
            trace_id=trace_id or self.trace_id,
            event_id=event_id,
        )

    def emit_many(
        self,
        event_types: Iterable[str],
        *,
        turn_id: str,
        attempt_id: str,
        **kwargs: Any,
    ) -> list[Envelope]:
        """Emit several envelopes for the same turn/attempt in order."""
        return [
            self.emit(et, turn_id=turn_id, attempt_id=attempt_id, **kwargs)
            for et in event_types
        ]


__all__ = [
    "PROTOCOL_VERSION",
    "PAYLOAD_VERSION",
    "REDACTION_NONE",
    "REDACTION_SECRET",
    "EXECUTION_CONTEXT_SCHEMA",
    "RUN_EVENT_SCHEMA",
    "LifecycleEvent",
    "PresentationEvent",
    "ExecutionEvent",
    "ControlCommand",
    "EVENT_FAMILIES",
    "VALID_EVENT_TYPES",
    "Envelope",
    "DuplicateEventError",
    "EventDeduplicator",
    "EventClassification",
    "SecretSafePayload",
    "ExecutionContext",
    "ReplayCursor",
    "RunEvent",
    "SequenceGapError",
    "IdempotencyConflictError",
    "ImmutableContextError",
    "ReplayProjection",
    "RunEventStream",
    "Emitter",
]
