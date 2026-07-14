"""Bounded operational self-model primitives for issue #139.

This module is an additive data contract, not an Agent-native memory
integration.  It deliberately does not import or own SessionDB, MemoryManager,
ContextEngine, GoalManager, Runtime receipts, transcripts, or prompt state.
The contract describes observable operational claims; it makes no claim about
consciousness, qualia, or a private chain of thought.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "simplicio.operational-self-model/v1"
MAX_RECORDS = 256
MAX_VIEW_RECORDS = 64
MAX_TEXT_LENGTH = 8_192
MAX_EVIDENCE_LINKS = 32
MAX_RELATION_LINKS = 64
MAX_VALUE_REPR_LENGTH = 16_384


class OperationalSelfModelError(ValueError):
    """Base error for invalid operational self-model data."""


class PromotionStatus(str, Enum):
    """How a claim entered the operational self-model."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    PROPOSED = "proposed"
    CURATED = "curated"


class Sensitivity(str, Enum):
    """Storage sensitivity used by the default profile boundary."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"


class SelfModelView(str, Enum):
    """Named operational views that a future Agent integration may project."""

    IDENTITY = "identity"
    CAPABILITY = "capability"
    GOAL = "goal"
    COMMITMENT = "commitment"
    PREFERENCE = "preference"
    LIMITATION = "limitation"
    PREDICTION = "prediction"
    REFLECTION = "reflection"
    LEARNING_PROPOSAL = "learning_proposal"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperationalSelfModelError(f"{name} must be a non-empty string")
    if len(value) > MAX_TEXT_LENGTH:
        raise OperationalSelfModelError(f"{name} exceeds {MAX_TEXT_LENGTH} characters")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperationalSelfModelError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _enum(value: Any, enum_type: type[Enum], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise OperationalSelfModelError(f"{name} must be one of: {choices}") from exc


def _bounded_ids(values: Iterable[str], name: str, limit: int) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise OperationalSelfModelError(f"{name} must be a collection of strings")
    try:
        result = tuple(_text(value, f"{name}[{index}]") for index, value in enumerate(values))
    except TypeError as exc:
        raise OperationalSelfModelError(f"{name} must be a collection") from exc
    if len(result) > limit:
        raise OperationalSelfModelError(f"{name} exceeds {limit} items")
    if len(result) != len(set(result)):
        raise OperationalSelfModelError(f"{name} contains duplicate ids")
    return result


@dataclass(frozen=True, slots=True)
class TemporalInterval:
    """A half-open, timezone-aware interval used for one temporal dimension."""

    start: datetime
    end: datetime | None = None

    def __post_init__(self) -> None:
        start = _aware(self.start, "interval.start")
        end = None if self.end is None else _aware(self.end, "interval.end")
        if end is not None and end <= start:
            raise OperationalSelfModelError("interval.end must be after interval.start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def contains(self, point: datetime) -> bool:
        point = _aware(point, "interval point")
        return self.start <= point and (self.end is None or point < self.end)


# The alias makes the bitemporal intent discoverable without adding a second
# interval implementation or a persistence dependency.
BitemporalInterval = TemporalInterval


@dataclass(frozen=True, slots=True)
class Freshness:
    """When a claim was observed and until when it may support a view."""

    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        observed_at = _aware(self.observed_at, "freshness.observed_at")
        expires_at = _aware(self.expires_at, "freshness.expires_at")
        if expires_at <= observed_at:
            raise OperationalSelfModelError("freshness.expires_at must be after observed_at")
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "expires_at", expires_at)

    def is_fresh(self, at: datetime) -> bool:
        return self.observed_at <= _aware(at, "freshness check") < self.expires_at


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """A bounded pointer to an external receipt, message, or observation.

    ``verified`` is deliberately explicit.  Without it, or an injected
    evidence checker, verification remains false; a string that merely looks
    like a receipt can never promote itself to truth.
    """

    id: str
    kind: str
    reference: str
    verified: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "evidence.id"))
        object.__setattr__(self, "kind", _text(self.kind, "evidence.kind"))
        object.__setattr__(self, "reference", _text(self.reference, "evidence.reference"))
        if not isinstance(self.verified, bool):
            raise OperationalSelfModelError("evidence.verified must be a boolean")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One bitemporal, provenance-bearing operational claim."""

    record_id: str
    subject: str
    predicate: str
    value: Any
    valid_time: TemporalInterval
    recorded_time: TemporalInterval
    provenance: tuple[EvidenceLink, ...]
    confidence: float
    freshness: Freshness
    scope: str = "default"
    profile: str = "default"
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    promotion: PromotionStatus = PromotionStatus.OBSERVED
    view: SelfModelView = SelfModelView.REFLECTION
    supersedes: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _text(self.record_id, "record_id"))
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        object.__setattr__(self, "predicate", _text(self.predicate, "predicate"))
        object.__setattr__(self, "scope", _text(self.scope, "scope"))
        object.__setattr__(self, "profile", _text(self.profile, "profile"))
        if not isinstance(self.valid_time, TemporalInterval):
            raise OperationalSelfModelError("valid_time must be a TemporalInterval")
        if not isinstance(self.recorded_time, TemporalInterval):
            raise OperationalSelfModelError("recorded_time must be a TemporalInterval")
        if not isinstance(self.freshness, Freshness):
            raise OperationalSelfModelError("freshness must be a Freshness")
        if isinstance(self.value, (str, bytes)) and len(self.value) > MAX_VALUE_REPR_LENGTH:
            raise OperationalSelfModelError("value exceeds the bounded representation limit")
        try:
            value_repr_length = len(repr(self.value))
        except Exception as exc:
            raise OperationalSelfModelError("value must have a bounded representation") from exc
        if value_repr_length > MAX_VALUE_REPR_LENGTH:
            raise OperationalSelfModelError("value exceeds the bounded representation limit")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise OperationalSelfModelError("confidence must be a number")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= self.confidence <= 1.0:
            raise OperationalSelfModelError("confidence must be finite and between 0 and 1")
        evidence = tuple(self.provenance)
        if len(evidence) == 0:
            raise OperationalSelfModelError("provenance is required")
        if len(evidence) > MAX_EVIDENCE_LINKS:
            raise OperationalSelfModelError(f"provenance exceeds {MAX_EVIDENCE_LINKS} items")
        if any(not isinstance(item, EvidenceLink) for item in evidence):
            raise OperationalSelfModelError("provenance must contain EvidenceLink values")
        if len({item.id for item in evidence}) != len(evidence):
            raise OperationalSelfModelError("provenance contains duplicate ids")
        object.__setattr__(self, "provenance", evidence)
        object.__setattr__(self, "sensitivity", _enum(self.sensitivity, Sensitivity, "sensitivity"))
        object.__setattr__(self, "promotion", _enum(self.promotion, PromotionStatus, "promotion"))
        object.__setattr__(self, "view", _enum(self.view, SelfModelView, "view"))
        supersedes = _bounded_ids(self.supersedes, "supersedes", MAX_RELATION_LINKS)
        contradicts = _bounded_ids(self.contradicts, "contradicts", MAX_RELATION_LINKS)
        if self.record_id in supersedes or self.record_id in contradicts:
            raise OperationalSelfModelError("a record cannot relate to itself")
        object.__setattr__(self, "supersedes", supersedes)
        object.__setattr__(self, "contradicts", contradicts)

    @property
    def evidence(self) -> tuple[EvidenceLink, ...]:
        """Compatibility spelling for callers that use the issue terminology."""

        return self.provenance

    @property
    def fresh_until(self) -> datetime:
        return self.freshness.expires_at

    def verification_gaps(
        self,
        *,
        now: datetime | None = None,
        as_of_recorded: datetime | None = None,
        evidence_checker: Callable[[EvidenceLink], bool] | None = None,
    ) -> tuple[str, ...]:
        """Return every reason this claim cannot be treated as verified.

        The default is intentionally fail-closed.  A checker exception or a
        false result is a verification gap, never a permissive fallback.
        """

        evaluation_time = _aware(now or datetime.now(timezone.utc), "verification time")
        gaps: list[str] = []
        if as_of_recorded is not None and not self.recorded_time.contains(as_of_recorded):
            gaps.append("recorded outside as-of interval")
        if not self.freshness.is_fresh(evaluation_time):
            gaps.append("stale freshness")
        for link in self.provenance:
            try:
                verified = evidence_checker(link) if evidence_checker is not None else link.verified
            except Exception:
                verified = False
            if not verified:
                gaps.append(f"unverified evidence: {link.id}")
        return tuple(gaps)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The auditable result of a fail-closed record verification."""

    record_id: str
    verified: bool
    gaps: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return "verified" if self.verified else "unverified"


@dataclass(frozen=True, slots=True)
class SelfModelSnapshot:
    """A bounded, immutable view frozen for one session incarnation."""

    session_incarnation: str
    records: tuple[MemoryRecord, ...]
    valid_at: datetime
    recorded_at: datetime
    view: SelfModelView | None = None


EvidenceChecker = Callable[[EvidenceLink], bool]


class OperationalSelfModel:
    """Bounded append-only store for verified operational claims.

    This class stores only contract records.  It is intentionally not wired
    into the Agent's existing memory or goal systems; a future integration can
    consume its typed query/snapshot boundary without changing those owners.
    """

    def __init__(
        self,
        *,
        max_records: int = MAX_RECORDS,
        max_view_records: int = MAX_VIEW_RECORDS,
        evidence_checker: EvidenceChecker | None = None,
    ) -> None:
        if not isinstance(max_records, int) or isinstance(max_records, bool) or not 1 <= max_records <= MAX_RECORDS:
            raise OperationalSelfModelError(f"max_records must be between 1 and {MAX_RECORDS}")
        if not isinstance(max_view_records, int) or isinstance(max_view_records, bool) or not 1 <= max_view_records <= MAX_VIEW_RECORDS:
            raise OperationalSelfModelError(f"max_view_records must be between 1 and {MAX_VIEW_RECORDS}")
        self.max_records = max_records
        self.max_view_records = max_view_records
        self._evidence_checker = evidence_checker
        self._records: dict[str, MemoryRecord] = {}

    @property
    def records(self) -> tuple[MemoryRecord, ...]:
        """Return all stored versions, including superseded contradictions."""

        return tuple(self._records.values())

    def append(self, record: MemoryRecord) -> MemoryRecord:
        """Append one immutable record without deleting prior versions."""

        if not isinstance(record, MemoryRecord):
            raise OperationalSelfModelError("record must be a MemoryRecord")
        if record.record_id in self._records:
            raise OperationalSelfModelError(f"duplicate record_id: {record.record_id}")
        for related_id in (*record.supersedes, *record.contradicts):
            if related_id not in self._records:
                raise OperationalSelfModelError(f"unknown related record: {related_id}")
        if len(self._records) >= self.max_records:
            raise OperationalSelfModelError("operational self-model record bound exceeded")
        self._records[record.record_id] = record
        return record

    add = append

    def supersede(self, previous_id: str, replacement: MemoryRecord) -> MemoryRecord:
        """Append a replacement while retaining the historical record."""

        return self._append_relation(previous_id, replacement, "supersedes")

    def contradict(self, previous_id: str, contradiction: MemoryRecord) -> MemoryRecord:
        """Append a contradiction while retaining both versions for audit."""

        return self._append_relation(previous_id, contradiction, "contradicts")

    def _append_relation(self, previous_id: str, record: MemoryRecord, field: str) -> MemoryRecord:
        previous_id = _text(previous_id, "previous_id")
        if previous_id not in self._records:
            raise OperationalSelfModelError(f"unknown related record: {previous_id}")
        relations = getattr(record, field)
        if previous_id not in relations:
            record = MemoryRecord(
                record_id=record.record_id,
                subject=record.subject,
                predicate=record.predicate,
                value=record.value,
                valid_time=record.valid_time,
                recorded_time=record.recorded_time,
                provenance=record.provenance,
                confidence=record.confidence,
                freshness=record.freshness,
                scope=record.scope,
                profile=record.profile,
                sensitivity=record.sensitivity,
                promotion=record.promotion,
                view=record.view,
                supersedes=record.supersedes + (previous_id,) if field == "supersedes" else record.supersedes,
                contradicts=record.contradicts + (previous_id,) if field == "contradicts" else record.contradicts,
            )
        return self.append(record)

    def verify(
        self,
        record_id: str,
        *,
        now: datetime | None = None,
        as_of_recorded: datetime | None = None,
    ) -> VerificationResult:
        """Verify one record; missing records fail closed."""

        record = self._records.get(record_id)
        if record is None:
            return VerificationResult(record_id=record_id, verified=False, gaps=("unknown record",))
        gaps = record.verification_gaps(
            now=now,
            as_of_recorded=as_of_recorded,
            evidence_checker=self._evidence_checker,
        )
        return VerificationResult(record_id=record_id, verified=not gaps, gaps=gaps)

    def query(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        valid_at: datetime | None = None,
        recorded_at: datetime | None = None,
        profile: str = "default",
        scope: str | None = None,
        view: SelfModelView | None = None,
        include_sensitive: bool = False,
        include_versions: bool = False,
        limit: int | None = None,
    ) -> tuple[MemoryRecord, ...]:
        """Return a bounded, verified, profile-isolated projection."""

        profile = _text(profile, "profile")
        if scope is not None:
            scope = _text(scope, "scope")
        if subject is not None:
            subject = _text(subject, "subject")
        if predicate is not None:
            predicate = _text(predicate, "predicate")
        if view is not None:
            view = _enum(view, SelfModelView, "view")
        if limit is None:
            limit = self.max_view_records
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= self.max_view_records:
            raise OperationalSelfModelError(f"limit must be between 1 and {self.max_view_records}")
        valid_at = _aware(valid_at or datetime.now(timezone.utc), "valid_at")
        recorded_at = _aware(recorded_at or datetime.now(timezone.utc), "recorded_at")
        candidates: list[MemoryRecord] = []
        for record in reversed(tuple(self._records.values())):
            if record.profile != profile or (scope is not None and record.scope != scope):
                continue
            if subject is not None and record.subject != subject:
                continue
            if predicate is not None and record.predicate != predicate:
                continue
            if view is not None and record.view is not view:
                continue
            if record.sensitivity is Sensitivity.SENSITIVE and not include_sensitive:
                continue
            if not record.valid_time.contains(valid_at):
                continue
            result = self.verify(record.record_id, now=recorded_at, as_of_recorded=recorded_at)
            if not result.verified:
                continue
            candidates.append(record)
        if not include_versions:
            superseded = {old_id for record in candidates for old_id in record.supersedes}
            candidates = [record for record in candidates if record.record_id not in superseded]
        return tuple(candidates[:limit])

    def snapshot(
        self,
        session_incarnation: str,
        *,
        valid_at: datetime | None = None,
        recorded_at: datetime | None = None,
        profile: str = "default",
        scope: str | None = None,
        view: SelfModelView | None = None,
        include_sensitive: bool = False,
        include_versions: bool = False,
        limit: int | None = None,
    ) -> SelfModelSnapshot:
        """Freeze a bounded query result for one session incarnation."""

        session_incarnation = _text(session_incarnation, "session_incarnation")
        valid_at = _aware(valid_at or datetime.now(timezone.utc), "valid_at")
        recorded_at = _aware(recorded_at or datetime.now(timezone.utc), "recorded_at")
        records = self.query(
            valid_at=valid_at,
            recorded_at=recorded_at,
            profile=profile,
            scope=scope,
            view=view,
            include_sensitive=include_sensitive,
            include_versions=include_versions,
            limit=limit,
        )
        return SelfModelSnapshot(
            session_incarnation=session_incarnation,
            records=records,
            valid_at=valid_at,
            recorded_at=recorded_at,
            view=view,
        )


__all__ = [
    "BitemporalInterval",
    "EvidenceChecker",
    "EvidenceLink",
    "Freshness",
    "MAX_RECORDS",
    "MAX_VIEW_RECORDS",
    "MemoryRecord",
    "OperationalSelfModel",
    "OperationalSelfModelError",
    "PromotionStatus",
    "SCHEMA_VERSION",
    "SelfModelSnapshot",
    "SelfModelView",
    "Sensitivity",
    "TemporalInterval",
    "VerificationResult",
]
