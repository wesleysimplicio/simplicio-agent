"""Deterministic belief fusion for bounded operational awareness.

This module models how the agent should reconcile multiple observations about
one subject without collapsing missing, stale, or conflicting input into false
certainty. The implementation is intentionally pure and small: it accepts typed
observations, applies versioned source reliability, and returns an explicit
resolution receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


BELIEF_STATE_SCHEMA = "simplicio.belief-state"
BELIEF_STATE_SCHEMA_VERSION = "simplicio.belief-state/v1"


class BeliefType(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    PREDICTED = "predicted"
    REMEMBERED = "remembered"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    EXPIRED = "expired"


class BeliefDecision(str, Enum):
    ACCEPT = "accept"
    CLARIFY = "clarify"
    BLOCK = "block"
    DEFER = "defer"


def _text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _unit_interval(value: Any, field_name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _default_confidence(belief_type: BeliefType) -> float:
    if belief_type is BeliefType.OBSERVED:
        return 0.9
    if belief_type is BeliefType.REMEMBERED:
        return 0.8
    if belief_type is BeliefType.INFERRED:
        return 0.7
    return 0.6


@dataclass(frozen=True, slots=True)
class SourceReliability:
    """Versioned reliability receipt for one sensor or source class."""

    source: str
    version: str
    reliability: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "reliability", _unit_interval(self.reliability, "reliability")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "version": self.version,
            "reliability": self.reliability,
        }


@dataclass(frozen=True, slots=True)
class BeliefObservation:
    """One explicit observation with provenance and time bounds."""

    subject: str
    source: str
    source_event_id: str
    value: Any | None = None
    distribution: tuple[tuple[str, float], ...] = ()
    belief_type: BeliefType = BeliefType.OBSERVED
    freshness: Freshness = Freshness.UNKNOWN
    confidence: float | None = None
    valid_time_ns: int | None = None
    system_time_ns: int | None = None
    expiry_ns: int | None = None
    missing: bool = False
    evidence_handles: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(
            self, "source_event_id", _text(self.source_event_id, "source_event_id")
        )
        if not isinstance(self.belief_type, BeliefType):
            object.__setattr__(self, "belief_type", BeliefType(self.belief_type))
        if not isinstance(self.freshness, Freshness):
            object.__setattr__(self, "freshness", Freshness(self.freshness))
        if self.confidence is not None:
            object.__setattr__(
                self, "confidence", _unit_interval(self.confidence, "confidence")
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
            "evidence_handles",
            tuple(
                sorted({
                    _text(item, "evidence_handle") for item in self.evidence_handles
                })
            ),
        )
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted({_text(item, "conflict") for item in self.conflicts})),
        )
        if self.missing and self.value is not None:
            raise ValueError("missing observations cannot carry a value")
        if self.missing and self.distribution:
            raise ValueError("missing observations cannot carry a distribution")
        if not self.missing and self.value is None and not self.distribution:
            raise ValueError(
                "observations must carry either a value, a distribution, or missing=True"
            )
        for name in ("valid_time_ns", "system_time_ns", "expiry_ns"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer when present")

    def canonical_value(self) -> str:
        if self.missing:
            return "<missing>"
        if self.distribution:
            return _stable_json({"distribution": self.distribution})
        return _stable_json(self.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "source": self.source,
            "source_event_id": self.source_event_id,
            "value": self.value,
            "distribution": [list(item) for item in self.distribution],
            "belief_type": self.belief_type.value,
            "freshness": self.freshness.value,
            "confidence": self.confidence,
            "valid_time_ns": self.valid_time_ns,
            "system_time_ns": self.system_time_ns,
            "expiry_ns": self.expiry_ns,
            "missing": self.missing,
            "evidence_handles": list(self.evidence_handles),
            "conflicts": list(self.conflicts),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BeliefObservation":
        return cls(
            subject=data["subject"],
            source=data["source"],
            source_event_id=data["source_event_id"],
            value=data.get("value"),
            distribution=tuple(tuple(item) for item in data.get("distribution", ())),
            belief_type=BeliefType(data.get("belief_type", BeliefType.OBSERVED.value)),
            freshness=Freshness(data.get("freshness", Freshness.UNKNOWN.value)),
            confidence=data.get("confidence"),
            valid_time_ns=data.get("valid_time_ns"),
            system_time_ns=data.get("system_time_ns"),
            expiry_ns=data.get("expiry_ns"),
            missing=bool(data.get("missing", False)),
            evidence_handles=tuple(data.get("evidence_handles", ())),
            conflicts=tuple(data.get("conflicts", ())),
        )

    def content_hash(self) -> str:
        return _fingerprint(self.to_dict())

    def to_fact(self, reliability: SourceReliability) -> "BeliefFact":
        base = (
            self.confidence
            if self.confidence is not None
            else _default_confidence(self.belief_type)
        )
        freshness_multiplier = {
            Freshness.FRESH: 1.0,
            Freshness.UNKNOWN: 0.85,
            Freshness.STALE: 0.55,
            Freshness.EXPIRED: 0.0,
        }[self.freshness]
        type_multiplier = {
            BeliefType.OBSERVED: 1.0,
            BeliefType.REMEMBERED: 0.92,
            BeliefType.INFERRED: 0.82,
            BeliefType.PREDICTED: 0.7,
        }[self.belief_type]
        confidence = _unit_interval(
            base * reliability.reliability * freshness_multiplier * type_multiplier,
            "confidence",
        )
        uncertainty = _unit_interval(1.0 - confidence, "uncertainty")
        return BeliefFact(
            subject=self.subject,
            value=self.value,
            distribution=self.distribution,
            source=self.source,
            source_event_id=self.source_event_id,
            source_version=reliability.version,
            belief_type=self.belief_type,
            freshness=self.freshness,
            confidence=confidence,
            uncertainty=uncertainty,
            valid_time_ns=self.valid_time_ns,
            system_time_ns=self.system_time_ns,
            expiry_ns=self.expiry_ns,
            missing=self.missing,
            evidence_handles=self.evidence_handles,
            conflicts=self.conflicts,
            evidence_to_change=(self.subject,)
            if self.missing
            else self.evidence_handles,
        )


@dataclass(frozen=True, slots=True)
class BeliefFact:
    """Materialized belief after fusion."""

    subject: str
    value: Any | None
    distribution: tuple[tuple[str, float], ...]
    source: str
    source_event_id: str
    source_version: str
    belief_type: BeliefType
    freshness: Freshness
    confidence: float
    uncertainty: float
    valid_time_ns: int | None
    system_time_ns: int | None
    expiry_ns: int | None
    missing: bool
    evidence_handles: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    evidence_to_change: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(
            self, "source_event_id", _text(self.source_event_id, "source_event_id")
        )
        object.__setattr__(
            self, "source_version", _text(self.source_version, "source_version")
        )
        if not isinstance(self.belief_type, BeliefType):
            object.__setattr__(self, "belief_type", BeliefType(self.belief_type))
        if not isinstance(self.freshness, Freshness):
            object.__setattr__(self, "freshness", Freshness(self.freshness))
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
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
            "evidence_handles",
            tuple(
                sorted({
                    _text(item, "evidence_handle") for item in self.evidence_handles
                })
            ),
        )
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted({_text(item, "conflict") for item in self.conflicts})),
        )
        object.__setattr__(
            self,
            "evidence_to_change",
            tuple(
                sorted({
                    _text(item, "evidence_to_change")
                    for item in self.evidence_to_change
                })
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "value": self.value,
            "distribution": [list(item) for item in self.distribution],
            "source": self.source,
            "source_event_id": self.source_event_id,
            "source_version": self.source_version,
            "belief_type": self.belief_type.value,
            "freshness": self.freshness.value,
            "confidence": self.confidence,
            "uncertainty": self.uncertainty,
            "valid_time_ns": self.valid_time_ns,
            "system_time_ns": self.system_time_ns,
            "expiry_ns": self.expiry_ns,
            "missing": self.missing,
            "evidence_handles": list(self.evidence_handles),
            "conflicts": list(self.conflicts),
            "evidence_to_change": list(self.evidence_to_change),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BeliefFact":
        return cls(
            subject=data["subject"],
            value=data.get("value"),
            distribution=tuple(tuple(item) for item in data.get("distribution", ())),
            source=data["source"],
            source_event_id=data["source_event_id"],
            source_version=data["source_version"],
            belief_type=BeliefType(data.get("belief_type", BeliefType.OBSERVED.value)),
            freshness=Freshness(data.get("freshness", Freshness.UNKNOWN.value)),
            confidence=data["confidence"],
            uncertainty=data["uncertainty"],
            valid_time_ns=data.get("valid_time_ns"),
            system_time_ns=data.get("system_time_ns"),
            expiry_ns=data.get("expiry_ns"),
            missing=bool(data.get("missing", False)),
            evidence_handles=tuple(data.get("evidence_handles", ())),
            conflicts=tuple(data.get("conflicts", ())),
            evidence_to_change=tuple(data.get("evidence_to_change", ())),
        )

    def content_hash(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class BeliefAssessment:
    """Fusion receipt for one subject."""

    subject: str
    decision: BeliefDecision
    facts: tuple[BeliefFact, ...]
    conflicts: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    uncertainty: float = 0.0
    reason: str = ""
    required_observation: str | None = None
    evidence_to_change: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        if not isinstance(self.decision, BeliefDecision):
            object.__setattr__(self, "decision", BeliefDecision(self.decision))
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted({_text(item, "conflict") for item in self.conflicts})),
        )
        object.__setattr__(
            self,
            "missing",
            tuple(sorted({_text(item, "missing") for item in self.missing})),
        )
        object.__setattr__(
            self, "uncertainty", _unit_interval(self.uncertainty, "uncertainty")
        )
        object.__setattr__(self, "reason", str(self.reason).strip())
        if self.required_observation is not None:
            object.__setattr__(
                self,
                "required_observation",
                _text(self.required_observation, "required_observation"),
            )
        object.__setattr__(
            self,
            "evidence_to_change",
            tuple(
                sorted({
                    _text(item, "evidence_to_change")
                    for item in self.evidence_to_change
                })
            ),
        )

    @property
    def selected_fact(self) -> BeliefFact | None:
        return self.facts[0] if self.facts else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "decision": self.decision.value,
            "facts": [fact.to_dict() for fact in self.facts],
            "conflicts": list(self.conflicts),
            "missing": list(self.missing),
            "uncertainty": self.uncertainty,
            "reason": self.reason,
            "required_observation": self.required_observation,
            "evidence_to_change": list(self.evidence_to_change),
        }


class BeliefStateEngine:
    """Fuse explicit observations into deterministic belief receipts."""

    def __init__(
        self,
        *,
        source_reliability: Mapping[str, SourceReliability] | None = None,
        clarify_threshold: float = 0.55,
        block_threshold: float = 0.35,
    ) -> None:
        self._source_reliability: dict[str, SourceReliability] = dict(
            source_reliability or {}
        )
        self.clarify_threshold = _unit_interval(clarify_threshold, "clarify_threshold")
        self.block_threshold = _unit_interval(block_threshold, "block_threshold")
        if self.block_threshold >= self.clarify_threshold:
            raise ValueError("block_threshold must be lower than clarify_threshold")

    def register_source(self, profile: SourceReliability) -> None:
        self._source_reliability[profile.source] = profile

    def reliability_for(self, source: str) -> SourceReliability:
        return self._source_reliability.get(source) or SourceReliability(
            source=source,
            version="default",
            reliability=0.5,
        )

    def fuse(
        self,
        observations: Sequence[BeliefObservation],
        *,
        subject: str | None = None,
        require_fresh: bool = False,
    ) -> BeliefAssessment:
        items = [
            item for item in observations if subject is None or item.subject == subject
        ]
        if subject is None and items:
            subject = items[0].subject
        if not items:
            subject = subject or "unknown"
            return BeliefAssessment(
                subject=subject,
                decision=BeliefDecision.DEFER,
                facts=(),
                missing=(subject,),
                uncertainty=1.0,
                reason="missing observation",
                required_observation=subject,
                evidence_to_change=(subject,),
            )

        facts = [
            item.to_fact(self.reliability_for(item.source))
            for item in items
            if not item.missing
        ]
        missing = tuple(sorted(item.subject for item in items if item.missing))

        if not facts:
            return BeliefAssessment(
                subject=subject or items[0].subject,
                decision=BeliefDecision.DEFER,
                facts=(),
                missing=missing or ((subject or items[0].subject),),
                uncertainty=1.0,
                reason="observation missing",
                required_observation=subject or items[0].subject,
                evidence_to_change=(subject or items[0].subject,),
            )

        facts.sort(
            key=lambda fact: (
                -fact.confidence,
                fact.freshness.value,
                fact.source_event_id,
                _stable_json(fact.value),
            )
        )
        selected = facts[0]
        canonical_payloads = {
            _stable_json(fact.value) if not fact.missing else "<missing>"
            for fact in facts
        }
        conflicts = tuple(
            sorted({
                f"{fact.subject}:{fact.source_event_id}"
                for fact in facts[1:]
                if _stable_json(fact.value) != _stable_json(selected.value)
                or fact.distribution != selected.distribution
            })
        )
        uncertainty = max(
            [fact.uncertainty for fact in facts] + ([1.0] if missing else [])
        )
        evidence_to_change = tuple(
            sorted(
                set(
                    fact.source_event_id
                    for fact in facts[1:]
                    if _stable_json(fact.value) != _stable_json(selected.value)
                    or fact.distribution != selected.distribution
                )
            )
        )
        has_conflict = len(canonical_payloads) > 1
        primary_fact = replace(
            selected,
            conflicts=conflicts,
            evidence_to_change=evidence_to_change or (selected.subject,),
            uncertainty=max(selected.uncertainty, uncertainty),
        )
        assessment_facts = (primary_fact,) + tuple(facts[1:])
        if selected.freshness in {Freshness.STALE, Freshness.EXPIRED} or require_fresh:
            if has_conflict:
                return BeliefAssessment(
                    subject=selected.subject,
                    decision=BeliefDecision.BLOCK
                    if require_fresh
                    else BeliefDecision.CLARIFY,
                    facts=assessment_facts,
                    conflicts=conflicts,
                    missing=missing,
                    uncertainty=max(uncertainty, 0.75),
                    reason="stale conflicting observation",
                    required_observation=selected.subject,
                    evidence_to_change=evidence_to_change or (selected.subject,),
                )
            return BeliefAssessment(
                subject=selected.subject,
                decision=BeliefDecision.BLOCK
                if require_fresh
                else BeliefDecision.DEFER,
                facts=assessment_facts,
                conflicts=conflicts,
                missing=missing,
                uncertainty=max(uncertainty, 0.8),
                reason="stale observation",
                required_observation=selected.subject,
                evidence_to_change=evidence_to_change or (selected.subject,),
            )

        if has_conflict:
            if selected.confidence >= self.clarify_threshold:
                decision = BeliefDecision.CLARIFY
            elif selected.confidence <= self.block_threshold:
                decision = BeliefDecision.BLOCK
            else:
                decision = BeliefDecision.DEFER
            return BeliefAssessment(
                subject=selected.subject,
                decision=decision,
                facts=assessment_facts,
                conflicts=conflicts,
                missing=missing,
                uncertainty=max(uncertainty, 0.65),
                reason="conflicting observations",
                required_observation=selected.subject,
                evidence_to_change=evidence_to_change or (selected.subject,),
            )

        if selected.confidence <= self.block_threshold:
            return BeliefAssessment(
                subject=selected.subject,
                decision=BeliefDecision.BLOCK,
                facts=assessment_facts,
                conflicts=conflicts,
                missing=missing,
                uncertainty=max(uncertainty, 0.9),
                reason="insufficient confidence",
                required_observation=selected.subject,
                evidence_to_change=evidence_to_change or (selected.subject,),
            )
        if selected.confidence < self.clarify_threshold:
            return BeliefAssessment(
                subject=selected.subject,
                decision=BeliefDecision.CLARIFY,
                facts=assessment_facts,
                conflicts=conflicts,
                missing=missing,
                uncertainty=max(uncertainty, 0.6),
                reason="confidence requires clarification",
                required_observation=selected.subject,
                evidence_to_change=evidence_to_change or (selected.subject,),
            )
        return BeliefAssessment(
            subject=selected.subject,
            decision=BeliefDecision.ACCEPT,
            facts=assessment_facts,
            conflicts=conflicts,
            missing=missing,
            uncertainty=uncertainty,
            reason="accepted",
            required_observation=None,
            evidence_to_change=evidence_to_change,
        )


__all__ = [
    "BELIEF_STATE_SCHEMA",
    "BELIEF_STATE_SCHEMA_VERSION",
    "BeliefAssessment",
    "BeliefDecision",
    "BeliefFact",
    "BeliefObservation",
    "BeliefStateEngine",
    "BeliefType",
    "Freshness",
    "SourceReliability",
]
