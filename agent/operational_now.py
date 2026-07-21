"""Materialized operational-now snapshot projection.

This module turns awareness receipts into a deterministic snapshot that keeps
freshness, conflicts, uncertainty, and degradation explicit. Snapshot replay is
pure: the same receipt log always yields the same hash, and a corrupt snapshot
is discarded in favor of rebuilding from the journal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from agent.belief_state import (
    BeliefAssessment,
    BeliefDecision,
    BeliefFact,
    BeliefObservation,
    BeliefStateEngine,
    BeliefType,
    Freshness,
    SourceReliability,
)
from agent.event_store import (
    AwarenessReceipt,
    OperationalEventStore,
    OperationalEventStoreCorruptError,
    OperationalScope,
    OperationalValueStatus,
)


OPERATIONAL_NOW_SCHEMA = "simplicio.operational-now"
OPERATIONAL_NOW_SCHEMA_VERSION = "simplicio.operational-now/v1"


class Degradation(str, Enum):
    NONE = "none"
    UNKNOWN = "unknown"
    STALE = "stale"
    CONFLICT = "conflict"
    BLOCKED = "blocked"


class FieldStatus(str, Enum):
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


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _field_status_from_receipt(receipt: AwarenessReceipt) -> FieldStatus:
    return {
        OperationalValueStatus.MEASURED: FieldStatus.MEASURED,
        OperationalValueStatus.CANON: FieldStatus.CANON,
        OperationalValueStatus.INFERRED: FieldStatus.INFERRED,
        OperationalValueStatus.PLANNED: FieldStatus.PLANNED,
        OperationalValueStatus.UNKNOWN: FieldStatus.UNKNOWN,
    }[receipt.status]


@dataclass(frozen=True, slots=True)
class OperationalField:
    """One materialized field in the operational-now snapshot."""

    path: str
    value: Any | None
    status: FieldStatus
    freshness: Freshness
    source_event_id: str
    handle: str
    confidence: float | None = None
    uncertainty: float | None = None
    missing: bool = False
    conflicts: tuple[str, ...] = ()
    evidence_handles: tuple[str, ...] = ()
    valid_time_ns: int | None = None
    system_time_ns: int | None = None
    expiry_ns: int | None = None
    degradation: Degradation = Degradation.NONE

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _text(self.path, "path"))
        object.__setattr__(
            self, "source_event_id", _text(self.source_event_id, "source_event_id")
        )
        object.__setattr__(self, "handle", _text(self.handle, "handle"))
        if not isinstance(self.status, FieldStatus):
            object.__setattr__(self, "status", FieldStatus(self.status))
        if not isinstance(self.freshness, Freshness):
            object.__setattr__(self, "freshness", Freshness(self.freshness))
        if self.confidence is not None:
            object.__setattr__(self, "confidence", float(self.confidence))
        if self.uncertainty is not None:
            object.__setattr__(self, "uncertainty", float(self.uncertainty))
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
        if not isinstance(self.degradation, Degradation):
            object.__setattr__(self, "degradation", Degradation(self.degradation))
        if self.missing and self.value is not None:
            raise ValueError("missing fields cannot carry a value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "value": self.value,
            "status": self.status.value,
            "freshness": self.freshness.value,
            "source_event_id": self.source_event_id,
            "handle": self.handle,
            "confidence": self.confidence,
            "uncertainty": self.uncertainty,
            "missing": self.missing,
            "conflicts": list(self.conflicts),
            "evidence_handles": list(self.evidence_handles),
            "valid_time_ns": self.valid_time_ns,
            "system_time_ns": self.system_time_ns,
            "expiry_ns": self.expiry_ns,
            "degradation": self.degradation.value,
        }

    def content_hash(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class OperationalNowSnapshot:
    """Deterministic materialization of the current operational state."""

    run_id: str
    profile_id: str
    tenant_id: str
    fields: dict[str, OperationalField]
    beliefs: dict[str, BeliefFact]
    materialized_at_ns: int
    source_event_count: int
    degradation: Degradation = Degradation.NONE
    conflicts: tuple[str, ...] = ()
    uncertainty: float = 0.0
    snapshot_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id"))
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(self, "tenant_id", _text(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "fields", dict(sorted(self.fields.items())))
        object.__setattr__(self, "beliefs", dict(sorted(self.beliefs.items())))
        if not isinstance(self.degradation, Degradation):
            object.__setattr__(self, "degradation", Degradation(self.degradation))
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted({_text(item, "conflict") for item in self.conflicts})),
        )
        object.__setattr__(self, "uncertainty", float(self.uncertainty))
        if not self.snapshot_hash:
            object.__setattr__(self, "snapshot_hash", self.content_hash())
        else:
            if self.snapshot_hash != self.content_hash():
                raise ValueError("snapshot_hash does not match snapshot content")

    def get(self, path: str) -> OperationalField | None:
        return self.fields.get(path)

    def resolve(self, handle: str) -> OperationalField | BeliefFact | None:
        handle = _text(handle, "handle")
        for field in self.fields.values():
            if field.handle == handle:
                return field
        for belief in self.beliefs.values():
            if belief.source_event_id == handle or belief.subject == handle:
                return belief
        return None

    def delta(self, previous: "OperationalNowSnapshot") -> dict[str, Any]:
        """Return a compact, deterministic field delta for incremental consumers."""

        if not isinstance(previous, OperationalNowSnapshot):
            raise TypeError("previous must be an OperationalNowSnapshot")
        changed = {
            path: field.to_dict()
            for path, field in self.fields.items()
            if previous.fields.get(path) != field
        }
        removed = sorted(set(previous.fields) - set(self.fields))
        changed_beliefs = {
            subject: belief.to_dict()
            for subject, belief in self.beliefs.items()
            if previous.beliefs.get(subject) != belief
        }
        removed_beliefs = sorted(set(previous.beliefs) - set(self.beliefs))
        return {
            "schema": OPERATIONAL_NOW_SCHEMA,
            "schema_version": OPERATIONAL_NOW_SCHEMA_VERSION,
            "from_hash": previous.snapshot_hash,
            "to_hash": self.snapshot_hash,
            "changed": changed,
            "removed": removed,
            "changed_beliefs": changed_beliefs,
            "removed_beliefs": removed_beliefs,
        }

    def _payload_dict(self, *, include_hash: bool) -> dict[str, Any]:
        return {
            "schema": OPERATIONAL_NOW_SCHEMA,
            "schema_version": OPERATIONAL_NOW_SCHEMA_VERSION,
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "tenant_id": self.tenant_id,
            "materialized_at_ns": self.materialized_at_ns,
            "source_event_count": self.source_event_count,
            "degradation": self.degradation.value,
            "conflicts": list(self.conflicts),
            "uncertainty": self.uncertainty,
            "fields": {key: field.to_dict() for key, field in self.fields.items()},
            "beliefs": {key: belief.to_dict() for key, belief in self.beliefs.items()},
            "snapshot_hash": self.snapshot_hash if include_hash else "",
        }

    def to_dict(self) -> dict[str, Any]:
        return self._payload_dict(include_hash=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OperationalNowSnapshot":
        return cls(
            run_id=data["run_id"],
            profile_id=data["profile_id"],
            tenant_id=data["tenant_id"],
            fields={
                key: OperationalField(**value)
                for key, value in data.get("fields", {}).items()
            },
            beliefs={
                key: BeliefFact.from_dict(value)
                for key, value in data.get("beliefs", {}).items()
            },
            materialized_at_ns=int(data["materialized_at_ns"]),
            source_event_count=int(data["source_event_count"]),
            degradation=Degradation(data.get("degradation", Degradation.NONE.value)),
            conflicts=tuple(data.get("conflicts", ())),
            uncertainty=float(data.get("uncertainty", 0.0)),
            snapshot_hash=data.get("snapshot_hash", ""),
        )

    def content_hash(self) -> str:
        return _fingerprint(self._payload_dict(include_hash=False))


def _select_degradation(
    *,
    field_degradations: Sequence[Degradation],
    belief_assessments: Sequence[BeliefAssessment],
) -> Degradation:
    if any(
        assessment.decision is BeliefDecision.BLOCK for assessment in belief_assessments
    ):
        return Degradation.BLOCKED
    if any(
        assessment.decision is BeliefDecision.CLARIFY
        for assessment in belief_assessments
    ):
        return Degradation.CONFLICT
    if any(degradation is Degradation.CONFLICT for degradation in field_degradations):
        return Degradation.CONFLICT
    if any(degradation is Degradation.STALE for degradation in field_degradations):
        return Degradation.STALE
    if any(degradation is Degradation.UNKNOWN for degradation in field_degradations):
        return Degradation.UNKNOWN
    return Degradation.NONE


class OperationalNowProjector:
    """Pure projection from receipts to a snapshot."""

    def __init__(
        self,
        *,
        source_reliability: Mapping[str, SourceReliability] | None = None,
        scope: OperationalScope | None = None,
    ) -> None:
        self._belief_engine = BeliefStateEngine(source_reliability=source_reliability)
        self.scope = scope

    def project(self, receipts: Sequence[AwarenessReceipt]) -> OperationalNowSnapshot:
        if self.scope is not None:
            for receipt in receipts:
                self.scope.validate_payload(receipt.payload)
        ordered = sorted(
            receipts, key=lambda receipt: (receipt.recorded_at_ns, receipt.receipt_id)
        )
        fields: dict[str, OperationalField] = {}
        belief_inputs: dict[str, list[BeliefObservation]] = {}
        field_degradations: list[Degradation] = []
        field_uncertainties: list[float] = []
        conflicts: set[str] = set()

        for receipt in ordered:
            if receipt.path.startswith("belief."):
                belief_inputs.setdefault(receipt.path, []).append(
                    BeliefObservation(
                        subject=receipt.path,
                        source=receipt.source,
                        source_event_id=receipt.source_event_id,
                        value=receipt.value,
                        distribution=receipt.distribution,
                        belief_type=receipt.belief_type,
                        freshness=receipt.freshness,
                        confidence=receipt.confidence,
                        valid_time_ns=receipt.valid_time_ns,
                        system_time_ns=receipt.system_time_ns,
                        expiry_ns=receipt.expiry_ns,
                        missing=receipt.missing,
                        evidence_handles=receipt.evidence_handles,
                        conflicts=receipt.conflicts,
                    )
                )
                continue

            field_degradation = {
                OperationalValueStatus.MEASURED: Degradation.NONE,
                OperationalValueStatus.CANON: Degradation.NONE,
                OperationalValueStatus.INFERRED: Degradation.UNKNOWN,
                OperationalValueStatus.PLANNED: Degradation.UNKNOWN,
                OperationalValueStatus.UNKNOWN: Degradation.UNKNOWN,
            }[receipt.status]
            if receipt.freshness in {Freshness.STALE, Freshness.EXPIRED}:
                field_degradation = Degradation.STALE
            if receipt.conflicts:
                field_degradation = Degradation.CONFLICT
            field = OperationalField(
                path=receipt.path,
                value=receipt.value,
                status=_field_status_from_receipt(receipt),
                freshness=receipt.freshness,
                source_event_id=receipt.source_event_id,
                handle=receipt.handle or receipt.path,
                confidence=receipt.confidence,
                uncertainty=receipt.uncertainty,
                missing=receipt.missing,
                conflicts=receipt.conflicts,
                evidence_handles=receipt.evidence_handles,
                valid_time_ns=receipt.valid_time_ns,
                system_time_ns=receipt.system_time_ns,
                expiry_ns=receipt.expiry_ns,
                degradation=field_degradation,
            )
            previous = fields.get(receipt.path)
            if previous is not None and previous.content_hash() != field.content_hash():
                conflicts.add(receipt.path)
                field = OperationalField(
                    path=field.path,
                    value=field.value,
                    status=field.status,
                    freshness=field.freshness,
                    source_event_id=field.source_event_id,
                    handle=field.handle,
                    confidence=field.confidence,
                    uncertainty=max(
                        field.uncertainty or 0.0, previous.uncertainty or 0.0, 0.5
                    ),
                    missing=field.missing,
                    conflicts=tuple(
                        sorted(
                            set(
                                previous.conflicts
                                + (previous.source_event_id, field.source_event_id)
                            )
                        )
                    ),
                    evidence_handles=tuple(
                        sorted(set(previous.evidence_handles + field.evidence_handles))
                    ),
                    valid_time_ns=field.valid_time_ns,
                    system_time_ns=field.system_time_ns,
                    expiry_ns=field.expiry_ns,
                    degradation=Degradation.CONFLICT,
                )
            fields[receipt.path] = field
            field_degradations.append(field.degradation)
            if field.uncertainty is not None:
                field_uncertainties.append(field.uncertainty)
            if field.conflicts:
                conflicts.add(receipt.path)

        belief_facts: dict[str, BeliefFact] = {}
        belief_assessments: list[BeliefAssessment] = []
        for subject, observations in belief_inputs.items():
            assessment = self._belief_engine.fuse(
                observations, subject=subject, require_fresh=False
            )
            belief_assessments.append(assessment)
            if assessment.selected_fact is not None:
                belief_facts[subject] = assessment.selected_fact
            if assessment.conflicts:
                conflicts.add(subject)

        for subject, assessment in sorted(
            ((item.subject, item) for item in belief_assessments),
            key=lambda pair: pair[0],
        ):
            if assessment.decision in {BeliefDecision.CLARIFY, BeliefDecision.BLOCK}:
                conflicts.add(subject)

        degradation = _select_degradation(
            field_degradations=field_degradations,
            belief_assessments=belief_assessments,
        )
        if degradation is Degradation.NONE and any(
            field.missing for field in fields.values()
        ):
            degradation = Degradation.UNKNOWN
        if degradation is Degradation.NONE and any(
            field.uncertainty and field.uncertainty > 0.5 for field in fields.values()
        ):
            degradation = Degradation.UNKNOWN
        uncertainty = 0.0
        if field_uncertainties:
            uncertainty = max(field_uncertainties)
        if belief_assessments:
            uncertainty = max(
                uncertainty,
                max(assessment.uncertainty for assessment in belief_assessments),
            )

        materialized_at_ns = ordered[-1].recorded_at_ns if ordered else 0
        if ordered:
            run_id = ordered[-1].payload.get("run_id", "unknown")
            profile_id = (
                self.scope.profile_id
                if self.scope is not None
                else ordered[-1].payload.get("profile_id", "unknown")
            )
            tenant_id = (
                self.scope.tenant_id
                if self.scope is not None
                else ordered[-1].payload.get("tenant_id", "unknown")
            )
        else:
            run_id = "unknown"
            profile_id = self.scope.profile_id if self.scope is not None else "unknown"
            tenant_id = self.scope.tenant_id if self.scope is not None else "unknown"
        snapshot = OperationalNowSnapshot(
            run_id=run_id,
            profile_id=profile_id,
            tenant_id=tenant_id,
            fields=fields,
            beliefs=belief_facts,
            materialized_at_ns=materialized_at_ns,
            source_event_count=len(ordered),
            degradation=degradation,
            conflicts=tuple(sorted(conflicts)),
            uncertainty=uncertainty,
        )
        return snapshot


class OperationalNowStore:
    """Receipt store plus materialized snapshot file with replay recovery."""

    def __init__(
        self,
        *,
        event_log_path: str | Path,
        snapshot_path: str | Path,
        scope: OperationalScope,
        source_reliability: Mapping[str, SourceReliability] | None = None,
    ) -> None:
        self.scope = scope
        self.event_store = OperationalEventStore(event_log_path, scope=scope)
        self.snapshot_path = Path(snapshot_path)
        self.source_reliability = dict(source_reliability or {})

    def append(self, receipt: AwarenessReceipt) -> AwarenessReceipt:
        return self.event_store.append(receipt)

    def project(self) -> OperationalNowSnapshot:
        projector = OperationalNowProjector(
            source_reliability=self.source_reliability,
            scope=self.scope,
        )
        snapshot = projector.project(list(self.event_store.iter_receipts()))
        self._write_snapshot(snapshot)
        return snapshot

    def _write_snapshot(self, snapshot: OperationalNowSnapshot) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )

    def load_snapshot(self) -> OperationalNowSnapshot:
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            snapshot = OperationalNowSnapshot.from_dict(payload)
        except FileNotFoundError:
            raise
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationalEventStoreCorruptError(
                f"cannot read snapshot: {exc}"
            ) from exc
        if snapshot.content_hash() != snapshot.snapshot_hash:
            raise OperationalEventStoreCorruptError("snapshot hash mismatch")
        if (
            snapshot.profile_id != self.scope.profile_id
            or snapshot.tenant_id != self.scope.tenant_id
        ):
            raise OperationalEventStoreCorruptError("snapshot scope mismatch")
        return snapshot

    def load_or_rebuild(self) -> OperationalNowSnapshot:
        try:
            return self.load_snapshot()
        except (FileNotFoundError, OperationalEventStoreCorruptError):
            return self.project()


__all__ = [
    "Degradation",
    "FieldStatus",
    "OPERATIONAL_NOW_SCHEMA",
    "OPERATIONAL_NOW_SCHEMA_VERSION",
    "OperationalField",
    "OperationalNowProjector",
    "OperationalNowSnapshot",
    "OperationalNowStore",
]
