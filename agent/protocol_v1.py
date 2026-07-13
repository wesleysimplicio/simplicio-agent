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
from typing import Any, Dict, Iterable, Optional

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
    "LifecycleEvent",
    "PresentationEvent",
    "ExecutionEvent",
    "ControlCommand",
    "EVENT_FAMILIES",
    "VALID_EVENT_TYPES",
    "Envelope",
    "DuplicateEventError",
    "EventDeduplicator",
    "Emitter",
]
