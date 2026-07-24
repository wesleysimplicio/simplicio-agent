"""Append-only awareness event store.

This store records awareness receipts and preserves them as JSONL so the
operational-now projection can be replayed deterministically. It deliberately
does not decide how to interpret the receipts; that logic lives in
``agent.operational_now`` and ``agent.belief_state``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from agent.belief_state import BeliefType, Freshness
from tools.hbi import (
    HbpLedger,
    ReceiptChain,
    pack_binary,
    parse_row,
    read_hbi,
    read_hbp,
    unpack_binary,
)


EVENT_STORE_SCHEMA = "simplicio.operational-event-store"
EVENT_STORE_SCHEMA_VERSION = "simplicio.operational-event-store/v1"
EXECUTION_CONTEXT_SCHEMA = "simplicio.execution-context/v1"
RUN_EVENT_SCHEMA = "simplicio.run-event/v1"
EVENT_STORE_MIGRATION_SCHEMA = "simplicio.operational-event-store-migration/v1"
DEFAULT_MIGRATION_MAX_BYTES = 16 * 1024 * 1024


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


class OperationalScopeError(ValueError):
    """Raised when a receipt is not owned by the store's scope."""


@dataclass(frozen=True, slots=True)
class OperationalScope:
    """Fail-closed profile/tenant boundary for an awareness store."""

    profile_id: str
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(self, "tenant_id", _text(self.tenant_id, "tenant_id"))

    def validate_payload(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise OperationalScopeError("receipt payload is missing store scope")
        for name, expected in (
            ("profile_id", self.profile_id),
            ("tenant_id", self.tenant_id),
        ):
            actual = payload.get(name)
            if not isinstance(actual, str) or not actual.strip():
                raise OperationalScopeError(f"receipt payload is missing {name}")
            if actual != expected:
                raise OperationalScopeError(
                    f"receipt {name} does not match store scope"
                )


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


@dataclass(frozen=True, slots=True)
class EventStoreMigrationReport:
    """Outcome of a legacy JSONL to local HBP/HBI migration."""

    legacy_path: Path
    target_path: Path
    receipt_count: int = 0
    source_digest: str | None = None
    target_digest: str | None = None
    migrated: bool = False
    already_migrated: bool = False
    rolled_back: bool = False
    skipped_reason: str | None = None
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _migration_paths(target_path: str | Path) -> tuple[Path, Path, Path, Path]:
    base = Path(target_path)
    return (
        base.with_suffix(".hbp"),
        base.with_suffix(".hbi"),
        base.with_suffix(".migration"),
        base.with_suffix(".migration.pending"),
    )


def _properties_text(values: Mapping[str, object]) -> str:
    return "".join(f"{key}={value}\n" for key, value in values.items())


def _read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise ValueError(f"invalid migration metadata line in {path}")
        values[key] = value
    return values


def _write_metadata(path: Path, values: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(_properties_text(values), encoding="utf-8")
    os.replace(temporary, path)


def _target_digest(hbp_path: Path, hbi_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(hbp_path.read_bytes())
    digest.update(b"\0")
    digest.update(hbi_path.read_bytes())
    return digest.hexdigest()


def _load_legacy_receipts(
    legacy_path: Path,
    scope: OperationalScope,
    max_bytes: int,
) -> tuple[list[AwarenessReceipt], str]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    try:
        size = legacy_path.stat().st_size
        if size > max_bytes:
            raise OperationalEventStoreCorruptError(
                f"legacy receipt log exceeds max_bytes ({size} > {max_bytes})"
            )
        raw = legacy_path.read_bytes()
    except OSError as exc:
        raise OperationalEventStoreCorruptError(
            f"cannot read legacy receipt log: {exc}"
        ) from exc
    if len(raw) > max_bytes:
        raise OperationalEventStoreCorruptError(
            f"legacy receipt log exceeds max_bytes ({len(raw)} > {max_bytes})"
        )
    source_digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OperationalEventStoreCorruptError(
            f"legacy receipt log is not valid UTF-8: {exc}"
        ) from exc

    receipts: list[AwarenessReceipt] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise TypeError("receipt must be a JSON object")
            receipt = AwarenessReceipt.from_dict(payload)
            scope.validate_payload(receipt.payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationalEventStoreCorruptError(
                f"legacy receipt log line {line_no}: {exc}"
            ) from exc
        receipts.append(receipt)
    return receipts, source_digest


def _decode_migrated_receipts(
    hbp_path: Path,
    hbi_path: Path,
    scope: OperationalScope,
) -> list[AwarenessReceipt]:
    rows = read_hbp(hbp_path)
    pointers = read_hbi(hbi_path)
    if len(rows) != len(pointers):
        raise OperationalEventStoreCorruptError(
            "HBP/HBI entry count mismatch"
        )
    if not ReceiptChain.verify_static(rows):
        raise OperationalEventStoreCorruptError("HBP receipt chain is invalid")
    offset = 0
    for pointer, row in zip(pointers, rows):
        row_size = len(row.encode("utf-8"))
        if pointer.off != offset or pointer.size != row_size:
            raise OperationalEventStoreCorruptError(
                "HBI pointer does not match the HBP row offsets"
            )
        offset += row_size + 1
    receipts: list[AwarenessReceipt] = []
    for row_no, row in enumerate(rows, start=1):
        tag, fields = parse_row(row)
        if tag != "AWARENESS":
            raise OperationalEventStoreCorruptError(
                f"HBP row {row_no} has unexpected tag {tag!r}"
            )
        values = dict(fields)
        try:
            payload = base64.b64decode(values["payload_b64"], validate=True)
            receipt = AwarenessReceipt.from_dict(unpack_binary(payload))
            scope.validate_payload(receipt.payload)
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise OperationalEventStoreCorruptError(
                f"HBP row {row_no} cannot be decoded: {exc}"
            ) from exc
        if values.get("receipt_id") != receipt.receipt_id:
            raise OperationalEventStoreCorruptError(
                f"HBP row {row_no} receipt_id does not match payload"
            )
        receipts.append(receipt)
    return receipts


def _cleanup_migration_temporary(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def migrate_legacy_event_store(
    legacy_path: str | Path,
    target_path: str | Path,
    *,
    scope: OperationalScope,
    max_bytes: int = DEFAULT_MIGRATION_MAX_BYTES,
) -> EventStoreMigrationReport:
    """Atomically migrate a legacy JSONL receipt log into local HBP/HBI files.

    The complete legacy file is parsed and round-tripped before publication.
    A pending line-oriented transaction marker makes a retry clean up a
    process interrupted between the HBP and HBI replacements.  The marker is
    deliberately local metadata; this slice does not assert Runtime HBI v1
    conformance.
    """
    legacy_path = Path(legacy_path)
    target_path = Path(target_path)
    hbp_path, hbi_path, marker_path, pending_path = _migration_paths(target_path)
    temporary_base = hbp_path.with_name(f".{hbp_path.stem}.migration-tmp")
    temporary_hbp = temporary_base.with_suffix(".hbp")
    temporary_hbi = temporary_base.with_suffix(".hbi")
    temporary_marker = marker_path.with_name(f".{marker_path.name}.tmp")
    base = {"legacy_path": legacy_path, "target_path": target_path}

    try:
        receipts, source_digest = _load_legacy_receipts(
            legacy_path, scope, max_bytes
        )
    except (OSError, OperationalEventStoreCorruptError, ValueError) as exc:
        return EventStoreMigrationReport(**base, errors=(str(exc),))

    _cleanup_migration_temporary(temporary_hbp, temporary_hbi, temporary_marker)
    try:
        if pending_path.exists():
            pending = _read_properties(pending_path)
            if pending.get("schema") != EVENT_STORE_MIGRATION_SCHEMA or pending.get(
                "source_sha256"
            ) != source_digest:
                return EventStoreMigrationReport(
                    **base,
                    source_digest=source_digest,
                    errors=("pending migration belongs to another source",),
                )
            _cleanup_migration_temporary(hbp_path, hbi_path, marker_path, pending_path)

        if marker_path.exists():
            metadata = _read_properties(marker_path)
            if metadata.get("schema") != EVENT_STORE_MIGRATION_SCHEMA:
                return EventStoreMigrationReport(
                    **base,
                    source_digest=source_digest,
                    errors=("unsupported event-store migration marker",),
                )
            if metadata.get("source_sha256") != source_digest:
                return EventStoreMigrationReport(
                    **base,
                    source_digest=source_digest,
                    errors=("migration marker source digest does not match",),
                )
            if not hbp_path.exists() or not hbi_path.exists():
                raise OperationalEventStoreCorruptError(
                    "migration marker exists but HBP/HBI target is incomplete"
                )
            decoded = _decode_migrated_receipts(hbp_path, hbi_path, scope)
            target_digest = _target_digest(hbp_path, hbi_path)
            if metadata.get("target_sha256") != target_digest or int(
                metadata.get("receipt_count", "-1")
            ) != len(decoded):
                raise OperationalEventStoreCorruptError(
                    "migration marker does not match verified HBP/HBI target"
                )
            if [item.to_dict() for item in decoded] != [
                item.to_dict() for item in receipts
            ]:
                raise OperationalEventStoreCorruptError(
                    "verified target does not match the legacy source"
                )
            return EventStoreMigrationReport(
                **base,
                receipt_count=len(receipts),
                source_digest=source_digest,
                target_digest=target_digest,
                already_migrated=True,
            )

        if hbp_path.exists() or hbi_path.exists():
            return EventStoreMigrationReport(
                **base,
                source_digest=source_digest,
                errors=("target exists without a matching migration marker",),
            )

        ledger = HbpLedger(temporary_base)
        for receipt in receipts:
            ledger.append(
                "AWARENESS",
                [
                    ("receipt_id", receipt.receipt_id),
                    (
                        "payload_b64",
                        base64.b64encode(pack_binary(receipt.to_dict())).decode(
                            "ascii"
                        ),
                    ),
                ],
            )
        ledger.flush()
        if not ledger.verify():
            raise OperationalEventStoreCorruptError("temporary HBP chain is invalid")
        decoded = _decode_migrated_receipts(temporary_hbp, temporary_hbi, scope)
        if [item.to_dict() for item in decoded] != [
            item.to_dict() for item in receipts
        ]:
            raise OperationalEventStoreCorruptError(
                "temporary HBP/HBI target does not match the legacy source"
            )
        target_digest = _target_digest(temporary_hbp, temporary_hbi)
        _write_metadata(
            pending_path,
            {
                "schema": EVENT_STORE_MIGRATION_SCHEMA,
                "source_sha256": source_digest,
                "receipt_count": len(receipts),
                "target_sha256": target_digest,
            },
        )
        os.replace(temporary_hbp, hbp_path)
        os.replace(temporary_hbi, hbi_path)
        _write_metadata(
            temporary_marker,
            {
                "schema": EVENT_STORE_MIGRATION_SCHEMA,
                "source_sha256": source_digest,
                "receipt_count": len(receipts),
                "target_sha256": target_digest,
            },
        )
        os.replace(temporary_marker, marker_path)
        pending_path.unlink(missing_ok=True)
        return EventStoreMigrationReport(
            **base,
            receipt_count=len(receipts),
            source_digest=source_digest,
            target_digest=target_digest,
            migrated=True,
        )
    except (OSError, ValueError, TypeError, OperationalEventStoreCorruptError) as exc:
        _cleanup_migration_temporary(temporary_hbp, temporary_hbi, temporary_marker)
        if pending_path.exists() and not marker_path.exists():
            _cleanup_migration_temporary(hbp_path, hbi_path, pending_path)
        return EventStoreMigrationReport(
            **base,
            receipt_count=len(receipts),
            source_digest=source_digest,
            rolled_back=True,
            errors=(str(exc),),
        )


def read_migrated_event_store(
    target_path: str | Path,
    *,
    scope: OperationalScope,
) -> list[AwarenessReceipt]:
    """Read and verify the local HBP/HBI representation of migrated receipts."""
    hbp_path, hbi_path, _marker_path, _pending_path = _migration_paths(target_path)
    if not hbp_path.exists() or not hbi_path.exists():
        raise OperationalEventStoreCorruptError("migrated HBP/HBI target is missing")
    return _decode_migrated_receipts(hbp_path, hbi_path, scope)


class OperationalEventStore:
    """Append-only JSONL journal for awareness receipts."""

    def __init__(self, path: str | Path, *, scope: OperationalScope) -> None:
        self.path = Path(path)
        if not isinstance(scope, OperationalScope):
            raise TypeError("scope must be an OperationalScope")
        self.scope = scope

    def append(self, receipt: AwarenessReceipt) -> AwarenessReceipt:
        self.scope.validate_payload(receipt.payload)
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
                receipt = AwarenessReceipt.from_dict(json.loads(line))
                self.scope.validate_payload(receipt.payload)
                receipts.append(receipt)
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
    "DEFAULT_MIGRATION_MAX_BYTES",
    "EXECUTION_CONTEXT_SCHEMA",
    "EVENT_STORE_SCHEMA",
    "EVENT_STORE_SCHEMA_VERSION",
    "EVENT_STORE_MIGRATION_SCHEMA",
    "EventStoreMigrationReport",
    "ExecutionContext",
    "migrate_legacy_event_store",
    "OperationalEventStore",
    "OperationalEventStoreCorruptError",
    "OperationalScope",
    "OperationalScopeError",
    "OperationalValueStatus",
    "read_migrated_event_store",
    "RUN_EVENT_SCHEMA",
    "RunEvent",
]
