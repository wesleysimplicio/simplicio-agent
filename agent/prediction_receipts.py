"""Deterministic prediction receipts for bounded effect reconciliation.

This is a pure contract layer.  It does not execute an action or a
counterfactual: callers provide observations after the existing action gate
has run, and :meth:`PredictionReceipt.assess` returns a new immutable receipt.
Unknown and error observations remain distinct from mismatches so a lost or
failed verifier cannot be learned as a false negative.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from agent.telemetry.receipts import Receipt, record_receipt


PREDICTION_RECEIPT_SCHEMA = "simplicio.prediction-receipt"
PREDICTION_RECEIPT_SCHEMA_VERSION = "simplicio.prediction-receipt/v1"
_COUNTERFACTUAL_EXECUTION = "model_only"
_MISSING = object()


class ObservationState(str, Enum):
    """The evidence state of an expected or observed value."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    ERROR = "error"


class PredictionOutcome(str, Enum):
    """Deterministic comparison result for one prediction receipt."""

    PENDING = "pending"
    MATCH = "match"
    PARTIAL_MATCH = "partial_match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    ERROR = "error"


class ReconciliationDecision(str, Enum):
    """Safe next step after comparing expected and observed effects."""

    PENDING = "pending"
    NONE = "none"
    RECONCILE = "reconcile"
    UPDATE_BELIEF = "update_belief"
    ESCALATE = "escalate"


class CounterfactualKind(str, Enum):
    """The compact alternatives represented without executing them."""

    NO_ACTION = "no_action"
    ALTERNATIVE = "alternative"


@dataclass(frozen=True)
class PredictionError:
    """A calibrated comparison result, including unresolved verifier state."""

    state: ObservationState
    rate: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        state = ObservationState(self.state)
        object.__setattr__(self, "state", state)
        if state is ObservationState.KNOWN:
            if (
                self.rate is None
                or not math.isfinite(self.rate)
                or not 0 <= self.rate <= 1
            ):
                raise ValueError(
                    "known prediction error requires a rate between 0 and 1"
                )
            if self.reason:
                raise ValueError("known prediction error cannot carry a reason")
        elif self.rate is not None or not self.reason.strip():
            raise ValueError(f"{state.value} prediction error requires a reason only")

    @classmethod
    def unknown(
        cls, reason: str = "prediction has not been assessed"
    ) -> "PredictionError":
        return cls(ObservationState.UNKNOWN, reason=reason)

    @classmethod
    def error(cls, reason: str) -> "PredictionError":
        return cls(ObservationState.ERROR, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"state": self.state.value}
        if self.rate is not None:
            result["rate"] = self.rate
        if self.reason:
            result["reason"] = self.reason
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PredictionError":
        return cls(
            state=ObservationState(value["state"]),
            rate=float(value["rate"]) if value.get("rate") is not None else None,
            reason=str(value.get("reason", "")),
        )


@dataclass(frozen=True)
class Observation:
    """One named, JSON-serializable effect observation."""

    key: str
    value: Any = _MISSING
    state: ObservationState = ObservationState.KNOWN
    reason: str = ""

    def __post_init__(self) -> None:
        key = self.key.strip()
        if not key:
            raise ValueError("observation key must be non-empty")
        object.__setattr__(self, "key", key)
        state = ObservationState(self.state)
        object.__setattr__(self, "state", state)
        if state is ObservationState.KNOWN:
            if self.value is _MISSING:
                raise ValueError("known observation requires a value")
            if self.reason:
                raise ValueError("known observation cannot carry a reason")
        elif self.value is not _MISSING or not self.reason.strip():
            raise ValueError(f"{state.value} observation requires a reason only")

    @classmethod
    def known(cls, key: str, value: Any) -> "Observation":
        return cls(key=key, value=value)

    @classmethod
    def unknown(cls, key: str, reason: str) -> "Observation":
        return cls(key=key, state=ObservationState.UNKNOWN, reason=reason)

    @classmethod
    def error(cls, key: str, reason: str) -> "Observation":
        return cls(key=key, state=ObservationState.ERROR, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"key": self.key, "state": self.state.value}
        if self.state is ObservationState.KNOWN:
            result["value"] = self.value
        else:
            result["reason"] = self.reason
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Observation":
        state = ObservationState(value["state"])
        if state is ObservationState.KNOWN:
            if "value" not in value:
                raise ValueError("known observation requires a serialized value")
            return cls.known(str(value["key"]), value["value"])
        return cls(
            key=str(value["key"]), state=state, reason=str(value.get("reason", ""))
        )


@dataclass(frozen=True)
class Counterfactual:
    """A declared model-only alternative; it has no execution capability."""

    kind: CounterfactualKind
    label: str
    outcome: Observation
    model: str
    execution: str = _COUNTERFACTUAL_EXECUTION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", CounterfactualKind(self.kind))
        object.__setattr__(
            self,
            "outcome",
            self.outcome
            if isinstance(self.outcome, Observation)
            else Observation.from_dict(self.outcome),
        )
        if not self.label.strip():
            raise ValueError("counterfactual label must be non-empty")
        if not self.model.strip():
            raise ValueError("counterfactual model must be declared")
        if self.execution != _COUNTERFACTUAL_EXECUTION:
            raise ValueError(
                "counterfactuals are model-only and cannot execute effects"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "outcome": self.outcome.to_dict(),
            "model": self.model,
            "execution": self.execution,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Counterfactual":
        return cls(
            kind=CounterfactualKind(value["kind"]),
            label=str(value["label"]),
            outcome=Observation.from_dict(value["outcome"]),
            model=str(value["model"]),
            execution=str(value.get("execution", _COUNTERFACTUAL_EXECUTION)),
        )


def _observations(
    values: Iterable[Observation | Mapping[str, Any]],
) -> tuple[Observation, ...]:
    result = tuple(
        value if isinstance(value, Observation) else Observation.from_dict(value)
        for value in values
    )
    keys = [value.key for value in result]
    if len(keys) != len(set(keys)):
        raise ValueError("observation keys must be unique")
    return tuple(sorted(result, key=lambda value: value.key))


@dataclass(frozen=True)
class PredictionReceipt:
    """Immutable pre/post-action prediction contract.

    Preconditions must point to a fresh belief or an existing receipt using
    ``belief:<ref>`` or ``receipt:<sha>``.  Expected effects are known,
    verifiable observations; ``must work`` is intentionally rejected as a
    non-observation.
    """

    action_digest: str
    preconditions: tuple[str, ...]
    expected_effects: tuple[Observation, ...]
    allowed_variance: Mapping[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    risk: str = ""
    cost_estimate: int = 0
    verifier: str = ""
    rollback: str = ""
    counterfactuals: tuple[Counterfactual, ...] = ()
    counterfactual_required: bool = True
    actual_observations: tuple[Observation, ...] = ()
    prediction_error: PredictionError = field(default_factory=PredictionError.unknown)
    outcome: PredictionOutcome = PredictionOutcome.PENDING
    reconciliation: ReconciliationDecision = ReconciliationDecision.PENDING
    update_decision: str = "pending"

    def __post_init__(self) -> None:
        if not self.action_digest.strip():
            raise ValueError("action_digest must be non-empty")
        preconditions = tuple(
            sorted(item.strip() for item in self.preconditions if item.strip())
        )
        if not preconditions:
            raise ValueError("preconditions must reference a belief or receipt")
        if any(not item.startswith(("belief:", "receipt:")) for item in preconditions):
            raise ValueError("preconditions must use belief:<ref> or receipt:<sha>")
        object.__setattr__(self, "preconditions", preconditions)

        expected = _observations(self.expected_effects)
        if not expected:
            raise ValueError("expected_effects must contain a verifiable observation")
        if any(item.state is not ObservationState.KNOWN for item in expected):
            raise ValueError("expected_effects cannot be unknown or error")
        if any(
            isinstance(item.value, str)
            and item.value.strip().casefold()
            in {"must work", "deve funcionar", "should work"}
            for item in expected
        ):
            raise ValueError("expected_effects must be verifiable observations")
        object.__setattr__(self, "expected_effects", expected)

        variance = {
            str(key): float(value) for key, value in self.allowed_variance.items()
        }
        expected_keys = {item.key for item in expected}
        if set(variance) - expected_keys:
            raise ValueError("allowed_variance may only name expected effects")
        if any(not math.isfinite(value) or value < 0 for value in variance.values()):
            raise ValueError("allowed variance must be finite and non-negative")
        object.__setattr__(self, "allowed_variance", dict(sorted(variance.items())))

        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if (
            not self.risk.strip()
            or not self.verifier.strip()
            or not self.rollback.strip()
        ):
            raise ValueError("risk, verifier, and rollback must be declared")
        if self.cost_estimate < 0:
            raise ValueError("cost_estimate must be non-negative")

        counterfactuals = tuple(
            item if isinstance(item, Counterfactual) else Counterfactual.from_dict(item)
            for item in self.counterfactuals
        )
        kinds = {item.kind for item in counterfactuals}
        if self.counterfactual_required and not {
            CounterfactualKind.NO_ACTION,
            CounterfactualKind.ALTERNATIVE,
        }.issubset(kinds):
            raise ValueError(
                "relevant actions require no_action and alternative counterfactuals"
            )
        object.__setattr__(
            self,
            "counterfactuals",
            tuple(
                sorted(counterfactuals, key=lambda item: (item.kind.value, item.label))
            ),
        )
        object.__setattr__(
            self, "actual_observations", _observations(self.actual_observations)
        )
        object.__setattr__(
            self,
            "prediction_error",
            self.prediction_error
            if isinstance(self.prediction_error, PredictionError)
            else PredictionError.from_dict(self.prediction_error),
        )
        object.__setattr__(self, "outcome", PredictionOutcome(self.outcome))
        object.__setattr__(
            self, "reconciliation", ReconciliationDecision(self.reconciliation)
        )
        if self.outcome is PredictionOutcome.PENDING:
            if (
                self.actual_observations
                or self.prediction_error.state is not ObservationState.UNKNOWN
                or self.reconciliation is not ReconciliationDecision.PENDING
                or self.update_decision != "pending"
            ):
                raise ValueError(
                    "pending prediction receipt cannot contain assessment data"
                )
        elif (
            self.reconciliation is ReconciliationDecision.PENDING
            or self.update_decision == "pending"
        ):
            raise ValueError("assessed prediction receipt requires reconciliation data")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PREDICTION_RECEIPT_SCHEMA,
            "schema_version": PREDICTION_RECEIPT_SCHEMA_VERSION,
            "action_digest": self.action_digest,
            "preconditions": list(self.preconditions),
            "expected_effects": [item.to_dict() for item in self.expected_effects],
            "allowed_variance": dict(self.allowed_variance),
            "confidence": self.confidence,
            "risk": self.risk,
            "cost_estimate": self.cost_estimate,
            "verifier": self.verifier,
            "rollback": self.rollback,
            "counterfactuals": [item.to_dict() for item in self.counterfactuals],
            "counterfactual_required": self.counterfactual_required,
            "actual_observations": [
                item.to_dict() for item in self.actual_observations
            ],
            "prediction_error": self.prediction_error.to_dict(),
            "outcome": self.outcome.value,
            "reconciliation": self.reconciliation.value,
            "update_decision": self.update_decision,
        }

    def to_json(self) -> str:
        """Return compact canonical JSON suitable for hashing and replay."""

        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PredictionReceipt":
        if value.get("schema") != PREDICTION_RECEIPT_SCHEMA:
            raise ValueError("unsupported prediction receipt schema")
        if value.get("schema_version") != PREDICTION_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported prediction receipt schema version")
        return cls(
            action_digest=str(value["action_digest"]),
            preconditions=tuple(value["preconditions"]),
            expected_effects=tuple(
                Observation.from_dict(item) for item in value["expected_effects"]
            ),
            allowed_variance=value.get("allowed_variance", {}),
            confidence=float(value["confidence"]),
            risk=str(value["risk"]),
            cost_estimate=int(value["cost_estimate"]),
            verifier=str(value["verifier"]),
            rollback=str(value["rollback"]),
            counterfactuals=tuple(
                Counterfactual.from_dict(item)
                for item in value.get("counterfactuals", ())
            ),
            counterfactual_required=bool(value.get("counterfactual_required", True)),
            actual_observations=tuple(
                Observation.from_dict(item)
                for item in value.get("actual_observations", ())
            ),
            prediction_error=PredictionError.from_dict(value["prediction_error"]),
            outcome=PredictionOutcome(value["outcome"]),
            reconciliation=ReconciliationDecision(value["reconciliation"]),
            update_decision=str(value["update_decision"]),
        )

    @classmethod
    def from_json(cls, text: str) -> "PredictionReceipt":
        return cls.from_dict(json.loads(text))

    def assess(
        self, observations: Iterable[Observation | Mapping[str, Any]]
    ) -> "PredictionReceipt":
        """Compare actual observations without retrying or executing anything."""

        if self.outcome is not PredictionOutcome.PENDING:
            raise ValueError("prediction receipt has already been assessed")
        actual = _observations(observations)
        actual_by_key = {item.key: item for item in actual}
        expected_by_key = {item.key: item for item in self.expected_effects}
        matched: list[str] = []
        mismatched: list[str] = []
        unresolved: list[str] = []
        errors: list[str] = []

        for key, expected in expected_by_key.items():
            observed = actual_by_key.get(key)
            if observed is None or observed.state is ObservationState.UNKNOWN:
                unresolved.append(key)
            elif observed.state is ObservationState.ERROR:
                errors.append(key)
            elif _matches(
                expected.value, observed.value, self.allowed_variance.get(key, 0.0)
            ):
                matched.append(key)
            else:
                mismatched.append(key)
        for key, observed in actual_by_key.items():
            if key not in expected_by_key:
                if observed.state is ObservationState.ERROR:
                    errors.append(key)
                elif observed.state is ObservationState.UNKNOWN:
                    unresolved.append(key)
                else:
                    mismatched.append(key)

        total = len(expected_by_key)
        if errors:
            outcome = PredictionOutcome.ERROR
            error = PredictionError.error(
                "verifier error for: " + ", ".join(sorted(errors))
            )
            reconciliation = ReconciliationDecision.ESCALATE
            update = "hold_and_escalate"
        elif unresolved:
            outcome = PredictionOutcome.UNKNOWN
            error = PredictionError.unknown(
                "observation unresolved for: " + ", ".join(sorted(unresolved))
            )
            reconciliation = ReconciliationDecision.RECONCILE
            update = "hold_until_reconciled"
        else:
            bad = len(mismatched)
            if not bad:
                outcome = PredictionOutcome.MATCH
                reconciliation = ReconciliationDecision.NONE
                update = "no_update"
            elif matched:
                outcome = PredictionOutcome.PARTIAL_MATCH
                reconciliation = ReconciliationDecision.UPDATE_BELIEF
                update = "update_belief_and_strategy"
            else:
                outcome = PredictionOutcome.MISMATCH
                reconciliation = ReconciliationDecision.UPDATE_BELIEF
                update = "update_belief_and_strategy"
            error = PredictionError(ObservationState.KNOWN, rate=bad / total)
        return replace(
            self,
            actual_observations=actual,
            prediction_error=error,
            outcome=outcome,
            reconciliation=reconciliation,
            update_decision=update,
        )

    def record_ledger(self, directory: str | Path | None = None) -> Receipt:
        """Link this canonical receipt to the existing content-addressed ledger."""

        return record_receipt(
            payload=self.to_json(),
            yool_id="agent.consciousness.prediction",
            lane="slow",
            status="error" if self.outcome is PredictionOutcome.ERROR else "ok",
            meta={
                "schema": PREDICTION_RECEIPT_SCHEMA,
                "action_digest": self.action_digest,
            },
            directory=Path(directory) if directory is not None else None,
        )


def _matches(expected: Any, observed: Any, variance: float) -> bool:
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(observed, (int, float))
        and not isinstance(observed, bool)
    ):
        return math.isclose(
            float(expected), float(observed), abs_tol=variance, rel_tol=0.0
        )
    return expected == observed


__all__ = [
    "PREDICTION_RECEIPT_SCHEMA",
    "PREDICTION_RECEIPT_SCHEMA_VERSION",
    "ObservationState",
    "PredictionOutcome",
    "ReconciliationDecision",
    "CounterfactualKind",
    "PredictionError",
    "Observation",
    "Counterfactual",
    "PredictionReceipt",
]
