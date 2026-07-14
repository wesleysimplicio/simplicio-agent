"""Append-only awareness event store.

This store records awareness receipts and preserves them as JSONL so the
operational-now projection can be replayed deterministically. It deliberately
does not decide how to interpret the receipts; that logic lives in
``agent.operational_now`` and ``agent.belief_state``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from agent.belief_state import BeliefType, Freshness


EVENT_STORE_SCHEMA = "simplicio.operational-event-store"
EVENT_STORE_SCHEMA_VERSION = "simplicio.operational-event-store/v1"
EXECUTION_CONTEXT_SCHEMA = "simplicio.execution-context/v1"
RUN_EVENT_SCHEMA = "simplicio.run-event/v1"


class OperationalValueStatus(str, Enum):
    MEASURED = "measured"
    CANON = "canon"
    INFERRED = "inferred"
    PLANNED = "planned"
    UNKNOWN = "unknown"


def _text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _unit_interval(value: Any, field_name: str) -> float:
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Canonical identity shared by Agent, Runtime, tools and providers."""

    profile_id: str
    tenant_id: str
    session_id: str
    run_id: str
    goal_hash: str
    anchor_hash: str
    phase: str
    step: int

    def __post_init__(self) -> None:
        for name in (
            "profile_id", "tenant_id", "session_id", "run_id",
            "goal_hash", "anchor_hash", "phase",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.step, int) or isinstance(self.step, bool) or self.step < 0:
            raise ValueError("step must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXECUTION_CONTEXT_SCHEMA,
            "profile_id": self.profile_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "goal_hash": self.goal_hash,
            "anchor_hash": self.anchor_hash,
            "phase": self.phase,
            "step": self.step,
        }

    def content_hash(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class RunEvent:
    """Append-only, idempotent event envelope for one execution context."""

    event_id: str
    run_id: str
    causal_parent: str | None
    sequence: int
    idempotency_key: str
    event_type: str
    actor: str
    source: str
    payload_ref: str
    classification: str
    receipt_hash: str | None = None
    schema_version: str = RUN_EVENT_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "event_id", "run_id", "idempotency_key", "event_type",
            "actor", "source", "payload_ref", "classification",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.causal_parent is not None:
            object.__setattr__(self, "causal_parent", _text(self.causal_parent, "causal_parent"))
        if self.receipt_hash is not None:
            object.__setattr__(self, "receipt_hash", _text(self.receipt_hash, "receipt_hash"))
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if self.schema_version != RUN_EVENT_SCHEMA:
            raise ValueError("unsupported run event schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "causal_parent": self.causal_parent,
            "sequence": self.sequence,
            "idempotency_key": self.idempotency_key,
            "event_type": self.event_type,
            "actor": self.actor,
            "source": self.source,
            "payload_ref": self.payload_ref,
            "classification": self.classification,
            "receipt_hash": self.receipt_hash,
        }

    def content_hash(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class AwarenessReceipt:
    """One append-only awareness receipt."""

    receipt_id: str
    path: str
    value: Any | None = None
    status: OperationalValueStatus = OperationalValueStatus.UNKNOWN
    freshness: Freshness = Freshness.UNKNOWN
    source: str = ""
    source_event_id: str = ""
    recorded_at_ns: int = 0
    handle: str | None = None
    belief_type: BeliefType = BeliefType.OBSERVED
    confidence: float | None = None
    uncertainty: float | None = None
    valid_time_ns: int | None = None
    system_time_ns: int | None = None
    expiry_ns: int | None = None
    missing: bool = False
    distribution: tuple[tuple[str, float], ...] = ()
    conflicts: tuple[str, ...] = ()
    evidence_handles: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "path", _text(self.path, "path"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(
            self, "source_event_id", _text(self.source_event_id, "source_event_id")
        )
        if self.handle is None:
            object.__setattr__(self, "handle", self.path)
        else:
            object.__setattr__(self, "handle", _text(self.handle, "handle"))
        if not isinstance(self.status, OperationalValueStatus):
            object.__setattr__(self, "status", OperationalValueStatus(self.status))
        if not isinstance(self.freshness, Freshness):
            object.__setattr__(self, "freshness", Freshness(self.freshness))
        if not isinstance(self.belief_type, BeliefType):
            object.__setattr__(self, "belief_type", BeliefType(self.belief_type))
        if self.confidence is not None:
            object.__setattr__(
                self, "confidence", _unit_interval(self.confidence, "confidence")
            )
        if self.uncertainty is not None:
            object.__setattr__(
                self, "uncertainty", _unit_interval(self.uncertainty, "uncertainty")
            )
        object.__setattr__(
            self,
            "distribution",
            tuple(
                sorted(
                    (
                        (
                            _text(label, "distribution_label"),
                            _unit_interval(prob, "distribution_probability"),
                        )
                        for label, prob in self.distribution
                    ),
                    key=lambda item: item[0],
                )
            ),
        )
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted({_text(item, "conflict") for item in self.conflicts})),
        )
        object.__setattr__(
            self,
            "evidence_handles",
            tuple(
                sorted({
                    _text(item, "evidence_handle") for item in self.evidence_handles
                })
            ),
        )
        if self.missing and self.value is not None:
            raise ValueError("missing receipts cannot also carry a value")
        if self.missing and self.distribution:
            raise ValueError("missing receipts cannot also carry a distribution")
        if (
            not isinstance(self.recorded_at_ns, int)
            or isinstance(self.recorded_at_ns, bool)
            or self.recorded_at_ns <= 0
        ):
            raise ValueError("recorded_at_ns must be a positive integer")
        for name in ("valid_time_ns", "system_time_ns", "expiry_ns"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer when present")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EVENT_STORE_SCHEMA,
            "schema_version": EVENT_STORE_SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "path": self.path,
            "value": self.value,
            "status": self.status.value,
            "freshness": self.freshness.value,
            "source": self.source,
            "source_event_id": self.source_event_id,
            "recorded_at_ns": self.recorded_at_ns,
            "handle": self.handle,
            "belief_type": self.belief_type.value,
            "confidence": self.confidence,
            "uncertainty": self.uncertainty,
            "valid_time_ns": self.valid_time_ns,
            "system_time_ns": self.system_time_ns,
            "expiry_ns": self.expiry_ns,
            "missing": self.missing,
            "distribution": [list(item) for item in self.distribution],
            "conflicts": list(self.conflicts),
            "evidence_handles": list(self.evidence_handles),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AwarenessReceipt":
        return cls(
            receipt_id=data["receipt_id"],
            path=data["path"],
            value=data.get("value"),
            status=OperationalValueStatus(
                data.get("status", OperationalValueStatus.UNKNOWN.value)
            ),
            freshness=Freshness(data.get("freshness", Freshness.UNKNOWN.value)),
            source=data["source"],
            source_event_id=data["source_event_id"],
            recorded_at_ns=int(data["recorded_at_ns"]),
            handle=data.get("handle"),
            belief_type=BeliefType(data.get("belief_type", BeliefType.OBSERVED.value)),
            confidence=data.get("confidence"),
            uncertainty=data.get("uncertainty"),
            valid_time_ns=data.get("valid_time_ns"),
            system_time_ns=data.get("system_time_ns"),
            expiry_ns=data.get("expiry_ns"),
            missing=bool(data.get("missing", False)),
            distribution=tuple(tuple(item) for item in data.get("distribution", ())),
            conflicts=tuple(data.get("conflicts", ())),
            evidence_handles=tuple(data.get("evidence_handles", ())),
            payload=dict(data.get("payload", {})),
        )

    def content_hash(self) -> str:
        return _fingerprint(self.to_dict())


class OperationalEventStoreCorruptError(ValueError):
    """Raised when the receipt journal cannot be replayed safely."""


class OperationalEventStore:
    """Append-only JSONL journal for awareness receipts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, receipt: AwarenessReceipt) -> AwarenessReceipt:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            )
        return receipt

    def iter_receipts(self) -> Iterable[AwarenessReceipt]:
        if not self.path.exists():
            return []
        receipts: list[AwarenessReceipt] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise OperationalEventStoreCorruptError(
                f"cannot read receipt log: {exc}"
            ) from exc
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                receipts.append(AwarenessReceipt.from_dict(json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise OperationalEventStoreCorruptError(
                    f"receipt log line {line_no}: {exc}"
                ) from exc
        return receipts

    def receipt_by_handle(self, handle: str) -> AwarenessReceipt | None:
        handle = _text(handle, "handle")
        for receipt in self.iter_receipts():
            if receipt.handle == handle:
                return receipt
        return None


__all__ = [
    "AwarenessReceipt",
    "EXECUTION_CONTEXT_SCHEMA",
    "EVENT_STORE_SCHEMA",
    "EVENT_STORE_SCHEMA_VERSION",
    "ExecutionContext",
    "OperationalEventStore",
    "OperationalEventStoreCorruptError",
    "OperationalValueStatus",
    "RUN_EVENT_SCHEMA",
    "RunEvent",
]
