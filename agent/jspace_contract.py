"""Bounded, typed state and trajectory contracts for J-Space.

This module deliberately describes an auditable product state space.  It does
not claim a geometric, quantum, or routing-benchmark result.  The contract is
additive: callers can record state and trajectory evidence without changing
the existing agent or recall implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any, Final, Mapping, Self


SCHEMA: Final[str] = "simplicio.j-space/v1"
AXES: Final[tuple[str, ...]] = (
    "task_progress",
    "uncertainty",
    "resource_pressure",
    "safety_risk",
    "evidence_coverage",
    "memory_novelty",
    "phase",
    "authorization",
)
_NUMERIC_AXES: Final[frozenset[str]] = frozenset(AXES[:6])


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field} must be a non-empty string")
    return value


def _require_unit_interval(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number in [0, 1]")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"{field} must be a finite number in [0, 1]")
    return number


def _canonical_value(value: Any) -> Any:
    """Return JSON-compatible data with deterministic ordering and types."""

    if hasattr(value, "to_dict"):
        return _canonical_value(value.to_dict())
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical data cannot contain NaN or infinity")
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize a contract value to stable UTF-8 JSON."""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_hash(value: Any) -> str:
    """Return the SHA-256 of a value's canonical JSON representation."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RoutingMetadata:
    """Evidence about a routing decision, without performing routing."""

    requested_capability: str
    candidate_ids: tuple[str, ...] = ()
    selected_id: str | None = None
    policy: str = "deterministic"
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.requested_capability, "requested_capability")
        _require_text(self.policy, "policy")
        if self.selected_id is not None:
            _require_text(self.selected_id, "selected_id")
        if self.reason is not None:
            _require_text(self.reason, "reason")
        if not isinstance(self.candidate_ids, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.candidate_ids
        ):
            raise TypeError("candidate_ids must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_capability": self.requested_capability,
            "candidate_ids": self.candidate_ids,
            "selected_id": self.selected_id,
            "policy": self.policy,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RecallMetadata:
    """Evidence about recall inputs and outputs, not a retrieval benchmark."""

    query_hash: str
    corpus_id: str
    candidate_ids: tuple[str, ...] = ()
    selected_ids: tuple[str, ...] = ()
    mode: str = "none"
    evidence_receipt: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.query_hash, "query_hash")
        _require_text(self.corpus_id, "corpus_id")
        _require_text(self.mode, "mode")
        if self.evidence_receipt is not None:
            _require_text(self.evidence_receipt, "evidence_receipt")
        for field, values in (
            ("candidate_ids", self.candidate_ids),
            ("selected_ids", self.selected_ids),
        ):
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise TypeError(f"{field} must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_hash": self.query_hash,
            "corpus_id": self.corpus_id,
            "candidate_ids": self.candidate_ids,
            "selected_ids": self.selected_ids,
            "mode": self.mode,
            "evidence_receipt": self.evidence_receipt,
        }


@dataclass(frozen=True, slots=True)
class JSpaceState:
    """One typed, immutable J-Space snapshot.

    The eight axes are explicit fields.  ``measured`` and ``unverified`` are
    explicit provenance sets, so inferred values cannot silently be presented
    as measured values.  The default marks the core axes as measured for the
    common case where a caller already has receipts for the snapshot.
    """

    task_progress: float
    uncertainty: float
    resource_pressure: float
    safety_risk: float
    evidence_coverage: float
    memory_novelty: float
    phase: str
    authorization: str
    measured: tuple[str, ...] = AXES
    unverified: tuple[str, ...] = ()
    routing: RoutingMetadata | None = None
    recall: RecallMetadata | None = None

    def __post_init__(self) -> None:
        for field in _NUMERIC_AXES:
            number = _require_unit_interval(getattr(self, field), field)
            object.__setattr__(self, field, number)
        _require_text(self.phase, "phase")
        _require_text(self.authorization, "authorization")
        for field, values in (("measured", self.measured), ("unverified", self.unverified)):
            if not isinstance(values, tuple):
                raise TypeError(f"{field} must be a tuple of axis names")
            if any(axis not in AXES for axis in values):
                raise ValueError(f"{field} contains an unknown axis")
            if len(set(values)) != len(values):
                raise ValueError(f"{field} contains duplicate axes")
        if set(self.measured) & set(self.unverified):
            raise ValueError("an axis cannot be both measured and unverified")
        if set(self.measured) | set(self.unverified) != set(AXES):
            raise ValueError("measured and unverified must classify every axis")
        if self.routing is not None and not isinstance(self.routing, RoutingMetadata):
            raise TypeError("routing must be RoutingMetadata or None")
        if self.recall is not None and not isinstance(self.recall, RecallMetadata):
            raise TypeError("recall must be RecallMetadata or None")

    @property
    def observed(self) -> tuple[str, ...]:
        """Alias that makes the measured/inferred boundary self-documenting."""

        return self.measured

    @property
    def inferred(self) -> tuple[str, ...]:
        return self.unverified

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "task_progress": self.task_progress,
            "uncertainty": self.uncertainty,
            "resource_pressure": self.resource_pressure,
            "safety_risk": self.safety_risk,
            "evidence_coverage": self.evidence_coverage,
            "memory_novelty": self.memory_novelty,
            "phase": self.phase,
            "authorization": self.authorization,
            "measured": self.measured,
            "unverified": self.unverified,
            "routing": self.routing,
            "recall": self.recall,
        }

    @property
    def canonical_json(self) -> str:
        return canonical_json(self)

    @property
    def canonical_bytes(self) -> bytes:
        return self.canonical_json.encode("utf-8")

    @property
    def content_hash(self) -> str:
        return content_hash(self)

    @property
    def state_id(self) -> str:
        return f"state:{self.content_hash}"


@dataclass(frozen=True, slots=True)
class Receipt:
    """A small, content-addressable proof attached to a transition."""

    kind: str
    value: str

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        _require_text(self.value, "value")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}

    @property
    def content_hash(self) -> str:
        return content_hash(self)


@dataclass(frozen=True, slots=True)
class JSpaceTransition:
    """A deterministic edge between two J-Space snapshots."""

    before: JSpaceState
    after: JSpaceState
    action: str
    anchor_hash: str
    receipt: Receipt
    cause: str

    def __post_init__(self) -> None:
        if not isinstance(self.before, JSpaceState) or not isinstance(self.after, JSpaceState):
            raise TypeError("before and after must be JSpaceState instances")
        _require_text(self.action, "action")
        _require_text(self.anchor_hash, "anchor_hash")
        if not isinstance(self.receipt, Receipt):
            raise TypeError("receipt must be a Receipt instance")
        _require_text(self.cause, "cause")

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before,
            "after": self.after,
            "action": self.action,
            "anchor_hash": self.anchor_hash,
            "receipt": self.receipt,
            "cause": self.cause,
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self)


@dataclass(frozen=True, slots=True)
class ReproducibilityCheck:
    """Measured result of validating a trajectory's hashes and replay chain."""

    reproducible: bool
    trajectory_id: str
    content_hash: str
    replay_hash: str
    errors: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.reproducible


@dataclass(frozen=True, slots=True)
class JSpaceTrajectory:
    """An immutable trajectory whose identity is derived from its contents."""

    initial_state: JSpaceState
    transitions: tuple[JSpaceTransition, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.initial_state, JSpaceState):
            raise TypeError("initial_state must be a JSpaceState instance")
        if not isinstance(self.transitions, tuple):
            raise TypeError("transitions must be a tuple")
        current = self.initial_state
        for index, transition in enumerate(self.transitions):
            if not isinstance(transition, JSpaceTransition):
                raise TypeError(f"transition {index} must be JSpaceTransition")
            if transition.before != current:
                raise ValueError(f"transition {index} does not continue the trajectory")
            current = transition.after

    @property
    def states(self) -> tuple[JSpaceState, ...]:
        return (self.initial_state,) + tuple(transition.after for transition in self.transitions)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "initial_state": self.initial_state, "transitions": self.transitions}

    @property
    def content_hash(self) -> str:
        return content_hash(self)

    @property
    def trajectory_id(self) -> str:
        return f"trajectory:{self.content_hash}"

    @property
    def canonical_json(self) -> str:
        return canonical_json(self)

    @property
    def canonical_bytes(self) -> bytes:
        return self.canonical_json.encode("utf-8")

    def append(self, transition: JSpaceTransition) -> Self:
        """Return a new trajectory after validating the transition edge."""

        expected = self.states[-1]
        if transition.before != expected:
            raise ValueError("transition does not start at the trajectory tail")
        return type(self)(self.initial_state, self.transitions + (transition,))

    def replay(self) -> tuple[JSpaceState, ...]:
        """Reconstruct states from the edge chain and fail closed on drift."""

        current = self.initial_state
        replayed = [current]
        for index, transition in enumerate(self.transitions):
            if transition.before != current:
                raise ValueError(f"trajectory replay drift at transition {index}")
            current = transition.after
            replayed.append(current)
        return tuple(replayed)

    def check_reproducibility(self) -> ReproducibilityCheck:
        errors: list[str] = []
        try:
            replayed = self.replay()
            replay_hash = content_hash(replayed)
        except (TypeError, ValueError) as error:
            replay_hash = ""
            errors.append(str(error))
        if not errors and replayed != self.states:
            errors.append("replay does not match the stored state sequence")
        return ReproducibilityCheck(
            reproducible=not errors,
            trajectory_id=self.trajectory_id,
            content_hash=self.content_hash,
            replay_hash=replay_hash,
            errors=tuple(errors),
        )

    def verify_reproducibility(self) -> ReproducibilityCheck:
        """Public alias for the measured reproducibility check."""

        return self.check_reproducibility()

    def assert_reproducible(self) -> None:
        result = self.check_reproducibility()
        if not result:
            raise ValueError("trajectory is not reproducible: " + "; ".join(result.errors))


__all__ = [
    "AXES",
    "SCHEMA",
    "JSpaceState",
    "JSpaceTransition",
    "JSpaceTrajectory",
    "RecallMetadata",
    "Receipt",
    "ReproducibilityCheck",
    "RoutingMetadata",
    "canonical_json",
    "content_hash",
]
