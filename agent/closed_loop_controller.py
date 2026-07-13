"""Pure closed-loop action policy primitives.

This module chooses the next *bounded* step from an explicit estimate and a
set of action candidates.  It never executes an action or changes authority:
the Runtime action gate remains the enforcement point.  Unknown, stale, or
conflicting state fails closed to observation, and a committed-but-unverified
effect always wins over retrying the candidate.

The contract is intentionally small so callers can feed it snapshots from
operational awareness (#160), goals from ``GoalContract`` (#147), and policy
from the universal action policy (#156) without creating another state store
or resource governor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


CONTROLLER_SCHEMA_VERSION = "simplicio.closed-loop-controller/v1"


class DecisionKind(str, Enum):
    """The only outcomes a controller may return."""

    ACTION = "action"
    OBSERVE = "observe"
    WAIT = "wait"
    CLARIFY = "clarify"
    BLOCK = "block"


class Freshness(str, Enum):
    """Freshness of the state boundary used for a decision."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class RiskClass(str, Enum):
    """Risk vocabulary shared with the action-policy boundary."""

    READ = "read"
    REVERSIBLE_WRITE = "reversible_write"
    INSTALL = "install"
    PROCESS_EXECUTION = "process_execution"
    EXTERNAL_COMMUNICATION = "external_communication"
    PUBLISH = "publish"
    DELETE = "delete"
    PAYMENT = "payment"
    CREDENTIAL = "credential"
    PRIVILEGE_ESCALATION = "privilege_escalation"


class ReasonCode(str, Enum):
    """Stable, user-safe reasons; these are not chain-of-thought."""

    ACTION_SELECTED = "action_selected"
    COMMITTED_EFFECT_REQUIRES_RECONCILIATION = (
        "committed_effect_requires_reconciliation"
    )
    CONFLICTING_OBSERVATIONS = "conflicting_observations"
    STATE_NOT_FRESH = "state_not_fresh"
    LOW_PRECONDITION_CONFIDENCE = "low_precondition_confidence"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    NO_ACTION_CANDIDATE = "no_action_candidate"
    HUMAN_GATE_REQUIRED = "human_gate_required"
    BUDGET_EXCEEDED = "budget_exceeded"
    MUTATION_DISABLED = "mutation_disabled"
    NO_SAFE_ACTION = "no_safe_action"


def _require_text(value: str, field_name: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _unit_interval(value: float, field_name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return value


def _nonnegative(value: float, field_name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


@dataclass(frozen=True)
class ActionCost:
    """Predicted cost receipt for one candidate action."""

    latency_ms: int
    tokens: int
    resource_units: float
    safety_risk: float
    irreversibility: float

    def __post_init__(self) -> None:
        if (
            not isinstance(self.latency_ms, int)
            or isinstance(self.latency_ms, bool)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be a non-negative integer")
        if (
            not isinstance(self.tokens, int)
            or isinstance(self.tokens, bool)
            or self.tokens < 0
        ):
            raise ValueError("tokens must be a non-negative integer")
        object.__setattr__(
            self, "resource_units", _nonnegative(self.resource_units, "resource_units")
        )
        object.__setattr__(
            self, "safety_risk", _unit_interval(self.safety_risk, "safety_risk")
        )
        object.__setattr__(
            self,
            "irreversibility",
            _unit_interval(self.irreversibility, "irreversibility"),
        )

    def to_dict(self) -> dict[str, int | float]:
        return {
            "latency_ms": self.latency_ms,
            "tokens": self.tokens,
            "resource_units": self.resource_units,
            "safety_risk": self.safety_risk,
            "irreversibility": self.irreversibility,
        }


@dataclass(frozen=True)
class ActionBudget:
    """Optional ceilings supplied by the existing resource governor."""

    latency_ms: int | None = None
    tokens: int | None = None
    resource_units: float | None = None

    def __post_init__(self) -> None:
        if self.latency_ms is not None and (
            not isinstance(self.latency_ms, int)
            or isinstance(self.latency_ms, bool)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms budget must be a non-negative integer")
        if self.tokens is not None and (
            not isinstance(self.tokens, int)
            or isinstance(self.tokens, bool)
            or self.tokens < 0
        ):
            raise ValueError("tokens budget must be a non-negative integer")
        if self.resource_units is not None:
            object.__setattr__(
                self,
                "resource_units",
                _nonnegative(self.resource_units, "resource_units budget"),
            )

    def exceeded(self, cost: ActionCost) -> tuple[str, ...]:
        exceeded: list[str] = []
        if self.latency_ms is not None and cost.latency_ms > self.latency_ms:
            exceeded.append("latency_ms")
        if self.tokens is not None and cost.tokens > self.tokens:
            exceeded.append("tokens")
        if (
            self.resource_units is not None
            and cost.resource_units > self.resource_units
        ):
            exceeded.append("resource_units")
        return tuple(exceeded)


@dataclass(frozen=True)
class StateEstimate:
    """Minimal explicit state boundary consumed by the policy."""

    freshness: Freshness = Freshness.UNKNOWN
    confidence: float | None = None
    conflicts: tuple[str, ...] = ()
    capability_available: bool = False
    effect_committed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.freshness, Freshness):
            object.__setattr__(self, "freshness", Freshness(self.freshness))
        if self.confidence is not None:
            object.__setattr__(
                self, "confidence", _unit_interval(self.confidence, "confidence")
            )
        object.__setattr__(
            self,
            "conflicts",
            tuple(_require_text(item, "conflict") for item in self.conflicts),
        )


@dataclass(frozen=True)
class ActionCandidate:
    """A proposed action with enough data for a safe, explainable choice."""

    action_digest: str
    predicted_effect: str
    cost: ActionCost
    verifier: str
    risk: RiskClass
    mutating: bool
    irreversible: bool
    expected_failure: float
    uncertainty: float
    requires_human_gate: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_digest", _require_text(self.action_digest, "action_digest")
        )
        object.__setattr__(
            self,
            "predicted_effect",
            _require_text(self.predicted_effect, "predicted_effect"),
        )
        object.__setattr__(self, "verifier", _require_text(self.verifier, "verifier"))
        if not isinstance(self.cost, ActionCost):
            raise TypeError("cost must be an ActionCost")
        if not isinstance(self.risk, RiskClass):
            object.__setattr__(self, "risk", RiskClass(self.risk))
        object.__setattr__(
            self,
            "expected_failure",
            _unit_interval(self.expected_failure, "expected_failure"),
        )
        object.__setattr__(
            self, "uncertainty", _unit_interval(self.uncertainty, "uncertainty")
        )


_DEFAULT_HUMAN_GATED_RISKS = frozenset({
    RiskClass.EXTERNAL_COMMUNICATION,
    RiskClass.PUBLISH,
    RiskClass.DELETE,
    RiskClass.PAYMENT,
    RiskClass.CREDENTIAL,
    RiskClass.PRIVILEGE_ESCALATION,
})


@dataclass(frozen=True)
class ControllerPolicy:
    """Versioned decision policy; no online tuning is performed here."""

    policy_version: str = CONTROLLER_SCHEMA_VERSION
    min_precondition_confidence: float = 0.8
    budget: ActionBudget = ActionBudget()
    allow_mutations: bool = True
    human_gated_risks: frozenset[RiskClass] = _DEFAULT_HUMAN_GATED_RISKS
    failure_weight: float = 1.0
    latency_weight: float = 1.0
    token_weight: float = 1.0
    resource_weight: float = 1.0
    safety_weight: float = 1.0
    irreversibility_weight: float = 1.0
    uncertainty_weight: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_version", _require_text(self.policy_version, "policy_version")
        )
        object.__setattr__(
            self,
            "min_precondition_confidence",
            _unit_interval(
                self.min_precondition_confidence, "min_precondition_confidence"
            ),
        )
        object.__setattr__(
            self,
            "human_gated_risks",
            frozenset(
                risk if isinstance(risk, RiskClass) else RiskClass(risk)
                for risk in self.human_gated_risks
            ),
        )
        for field_name in (
            "failure_weight",
            "latency_weight",
            "token_weight",
            "resource_weight",
            "safety_weight",
            "irreversibility_weight",
            "uncertainty_weight",
        ):
            object.__setattr__(
                self, field_name, _nonnegative(getattr(self, field_name), field_name)
            )

    def score(self, candidate: ActionCandidate) -> float:
        """Return the deterministic, versioned ordering score for a candidate."""

        cost = candidate.cost
        return (
            self.failure_weight * candidate.expected_failure
            + self.latency_weight * cost.latency_ms
            + self.token_weight * cost.tokens
            + self.resource_weight * cost.resource_units
            + self.safety_weight * cost.safety_risk
            + self.irreversibility_weight * cost.irreversibility
            + self.uncertainty_weight * candidate.uncertainty
        )


@dataclass(frozen=True)
class ControllerDecision:
    """Safe-to-serialize decision and prediction receipt."""

    kind: DecisionKind
    reason_code: ReasonCode
    policy_version: str
    alternatives_considered: tuple[str, ...] = ()
    action_digest: str = ""
    predicted_effect: str = ""
    predicted_cost: ActionCost | None = None
    risk: RiskClass | None = None
    verifier: str = ""
    requires_human_gate: bool = False
    score: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": CONTROLLER_SCHEMA_VERSION,
            "kind": self.kind.value,
            "reason_code": self.reason_code.value,
            "policy_version": self.policy_version,
            "alternatives_considered": list(self.alternatives_considered),
            "action_digest": self.action_digest,
            "predicted_effect": self.predicted_effect,
            "predicted_cost": self.predicted_cost.to_dict()
            if self.predicted_cost
            else None,
            "risk": self.risk.value if self.risk else None,
            "verifier": self.verifier,
            "requires_human_gate": self.requires_human_gate,
            "score": self.score,
        }


class ClosedLoopController:
    """Pure policy evaluator; callers own execution and observation."""

    def __init__(self, policy: ControllerPolicy | None = None) -> None:
        self.policy = policy or ControllerPolicy()

    def decide(
        self,
        goal: str,
        state: StateEstimate,
        candidates: Iterable[ActionCandidate],
    ) -> ControllerDecision:
        """Select one bounded step, or fail closed with a reason code.

        Candidate order is deliberately ignored.  Ties are resolved by the
        action digest, making replay independent of discovery order.
        """

        _require_text(goal, "goal")
        ordered = tuple(sorted(candidates, key=lambda item: item.action_digest))
        alternatives = tuple(item.action_digest for item in ordered)

        if state.effect_committed:
            return self._decision(
                DecisionKind.OBSERVE,
                ReasonCode.COMMITTED_EFFECT_REQUIRES_RECONCILIATION,
                alternatives,
            )
        if state.conflicts:
            return self._decision(
                DecisionKind.OBSERVE,
                ReasonCode.CONFLICTING_OBSERVATIONS,
                alternatives,
            )
        if state.freshness is not Freshness.FRESH:
            return self._decision(
                DecisionKind.OBSERVE, ReasonCode.STATE_NOT_FRESH, alternatives
            )
        if (
            state.confidence is None
            or state.confidence < self.policy.min_precondition_confidence
        ):
            return self._decision(
                DecisionKind.OBSERVE,
                ReasonCode.LOW_PRECONDITION_CONFIDENCE,
                alternatives,
            )
        if not state.capability_available:
            return self._decision(
                DecisionKind.WAIT, ReasonCode.CAPABILITY_UNAVAILABLE, alternatives
            )
        if not ordered:
            return self._decision(
                DecisionKind.OBSERVE, ReasonCode.NO_ACTION_CANDIDATE, alternatives
            )

        safe: list[ActionCandidate] = []
        gated: list[ActionCandidate] = []
        budget_blocked = False
        mutation_blocked = False
        for candidate in ordered:
            if self.policy.budget.exceeded(candidate.cost):
                budget_blocked = True
                continue
            if candidate.mutating and not self.policy.allow_mutations:
                mutation_blocked = True
                continue
            requires_gate = (
                candidate.requires_human_gate
                or candidate.risk in self.policy.human_gated_risks
                or candidate.irreversible
            )
            if requires_gate:
                gated.append(candidate)
            else:
                safe.append(candidate)

        if safe:
            selected = min(
                safe, key=lambda item: (self.policy.score(item), item.action_digest)
            )
            return self._decision(
                DecisionKind.ACTION,
                ReasonCode.ACTION_SELECTED,
                alternatives,
                selected,
                score=self.policy.score(selected),
            )
        if budget_blocked:
            return self._decision(
                DecisionKind.BLOCK, ReasonCode.BUDGET_EXCEEDED, alternatives
            )
        if gated:
            selected = min(
                gated, key=lambda item: (self.policy.score(item), item.action_digest)
            )
            return self._decision(
                DecisionKind.CLARIFY,
                ReasonCode.HUMAN_GATE_REQUIRED,
                alternatives,
                selected,
                requires_human_gate=True,
                score=self.policy.score(selected),
            )
        if mutation_blocked:
            return self._decision(
                DecisionKind.BLOCK, ReasonCode.MUTATION_DISABLED, alternatives
            )
        return self._decision(
            DecisionKind.BLOCK, ReasonCode.NO_SAFE_ACTION, alternatives
        )

    def _decision(
        self,
        kind: DecisionKind,
        reason_code: ReasonCode,
        alternatives: tuple[str, ...],
        candidate: ActionCandidate | None = None,
        *,
        requires_human_gate: bool = False,
        score: float | None = None,
    ) -> ControllerDecision:
        return ControllerDecision(
            kind=kind,
            reason_code=reason_code,
            policy_version=self.policy.policy_version,
            alternatives_considered=alternatives,
            action_digest=candidate.action_digest if candidate else "",
            predicted_effect=candidate.predicted_effect if candidate else "",
            predicted_cost=candidate.cost if candidate else None,
            risk=candidate.risk if candidate else None,
            verifier=candidate.verifier if candidate else "",
            requires_human_gate=requires_human_gate,
            score=score,
        )


__all__ = [
    "CONTROLLER_SCHEMA_VERSION",
    "ActionBudget",
    "ActionCandidate",
    "ActionCost",
    "ClosedLoopController",
    "ControllerDecision",
    "ControllerPolicy",
    "DecisionKind",
    "Freshness",
    "ReasonCode",
    "RiskClass",
    "StateEstimate",
]
