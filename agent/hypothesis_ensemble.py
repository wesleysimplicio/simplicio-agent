"""Bounded, deterministic evidence pruning for hypothesis ensembles.

The contract in this module is deliberately narrower than inference.  It does
not generate hypotheses, assign probabilities, or use sampling temperature as
evidence.  It only validates a bounded set of candidates and records which
candidates have enough explicit refuting evidence to be pruned.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable


HYPOTHESIS_PRUNING_SCHEMA_VERSION = "simplicio.hypothesis-pruning/v1"
HYPOTHESIS_PRUNING_POLICY_VERSION = "explicit-evidence-margin/v1"


def _text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _unit_interval(value: Any, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return number


def _temperature(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 2.0:
        raise ValueError("temperature must be finite and between 0 and 2")
    return number


def _handles(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    return tuple(sorted({_text(value, field_name) for value in values}))


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HypothesisCandidate:
    """One sampled hypothesis and the evidence currently attached to it."""

    hypothesis_id: str
    statement: str
    confidence: float
    temperature: float
    supporting_evidence: tuple[str, ...] = ()
    refuting_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hypothesis_id", _text(self.hypothesis_id, "hypothesis_id")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        object.__setattr__(self, "temperature", _temperature(self.temperature))
        object.__setattr__(
            self,
            "supporting_evidence",
            _handles(self.supporting_evidence, "supporting_evidence"),
        )
        object.__setattr__(
            self,
            "refuting_evidence",
            _handles(self.refuting_evidence, "refuting_evidence"),
        )
        overlap = set(self.supporting_evidence) & set(self.refuting_evidence)
        if overlap:
            raise ValueError(
                "evidence handles cannot both support and refute a hypothesis: "
                + ", ".join(sorted(overlap))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "confidence": self.confidence,
            "temperature": self.temperature,
            "supporting_evidence": list(self.supporting_evidence),
            "refuting_evidence": list(self.refuting_evidence),
        }


@dataclass(frozen=True, slots=True)
class HypothesisPruneRecord:
    """Auditable evidence for one prune decision."""

    hypothesis_id: str
    reason: str
    supporting_evidence: tuple[str, ...]
    refuting_evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "reason": self.reason,
            "supporting_evidence": list(self.supporting_evidence),
            "refuting_evidence": list(self.refuting_evidence),
        }


@dataclass(frozen=True, slots=True)
class HypothesisPruningReceipt:
    """Canonical receipt for a bounded evidence-pruning pass."""

    candidates: tuple[HypothesisCandidate, ...]
    kept_ids: tuple[str, ...]
    pruned: tuple[HypothesisPruneRecord, ...]
    minimum_refutations: int
    max_candidates: int

    @property
    def input_hash(self) -> str:
        return _fingerprint([candidate.to_dict() for candidate in self.candidates])

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": HYPOTHESIS_PRUNING_SCHEMA_VERSION,
            "policy_version": HYPOTHESIS_PRUNING_POLICY_VERSION,
            "input_hash": self.input_hash,
            "minimum_refutations": self.minimum_refutations,
            "max_candidates": self.max_candidates,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "kept_ids": list(self.kept_ids),
            "pruned": [record.to_dict() for record in self.pruned],
        }

    @property
    def receipt_hash(self) -> str:
        return _fingerprint(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_hash": self.receipt_hash}


def prune_hypothesis_ensemble(
    candidates: Iterable[HypothesisCandidate],
    *,
    minimum_refutations: int = 1,
    max_candidates: int = 8,
) -> HypothesisPruningReceipt:
    """Prune only hypotheses whose explicit refutations outweigh support.

    Confidence and sampling temperature are recorded but never used as prune
    evidence.  This prevents a low-confidence or high-temperature sample from
    disappearing without an auditable contradictory receipt.
    """

    if (
        not isinstance(minimum_refutations, int)
        or isinstance(minimum_refutations, bool)
        or minimum_refutations < 1
    ):
        raise ValueError("minimum_refutations must be a positive integer")
    if (
        not isinstance(max_candidates, int)
        or isinstance(max_candidates, bool)
        or max_candidates < 2
    ):
        raise ValueError("max_candidates must be an integer of at least 2")

    ordered = tuple(sorted(candidates, key=lambda item: item.hypothesis_id))
    if len(ordered) < 2:
        raise ValueError("a hypothesis ensemble must contain at least 2 candidates")
    if len(ordered) > max_candidates:
        raise ValueError(
            f"hypothesis ensemble exceeds max_candidates={max_candidates}"
        )
    ids = [candidate.hypothesis_id for candidate in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("hypothesis_id values must be unique")

    kept_ids: list[str] = []
    pruned: list[HypothesisPruneRecord] = []
    for candidate in ordered:
        refutations = len(candidate.refuting_evidence)
        support = len(candidate.supporting_evidence)
        if refutations >= minimum_refutations and refutations > support:
            pruned.append(
                HypothesisPruneRecord(
                    hypothesis_id=candidate.hypothesis_id,
                    reason="explicit_refutations_outweigh_support",
                    supporting_evidence=candidate.supporting_evidence,
                    refuting_evidence=candidate.refuting_evidence,
                )
            )
        else:
            kept_ids.append(candidate.hypothesis_id)

    return HypothesisPruningReceipt(
        candidates=ordered,
        kept_ids=tuple(kept_ids),
        pruned=tuple(pruned),
        minimum_refutations=minimum_refutations,
        max_candidates=max_candidates,
    )


__all__ = [
    "HYPOTHESIS_PRUNING_POLICY_VERSION",
    "HYPOTHESIS_PRUNING_SCHEMA_VERSION",
    "HypothesisCandidate",
    "HypothesisPruneRecord",
    "HypothesisPruningReceipt",
    "prune_hypothesis_ensemble",
]
