"""Pure closed-loop controller contract for bounded next-step decisions.

This module is intentionally narrow: it accepts a typed state estimate,
candidate actions, anti-oscillation signals, and a versioned policy.  It
returns one bounded decision for the *next* observation boundary only.  The
controller never executes tools, mutates state stores, or bypasses the Runtime
action gate.

Missing, stale, conflicting, or otherwise insufficient state fails closed to
observe/wait/clarify/block outcomes.  A committed-but-unverified effect wins
over retrying the same action, and repeated failure fingerprints can suppress
oscillating retries until a different strategy is chosen.  The optional
horizon contract validates only the leading predicted step, requires replanning
after a match, and emits a caller-owned rollback intent after divergence.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


CONTROLLER_SCHEMA_VERSION = "simplicio.closed-loop-controller/v1"
HORIZON_SCHEMA_VERSION = "simplicio.closed-loop-horizon/v1"


class DecisionKind(str, Enum):
    ACTION = "action"
    OBSERVE = "observe"
    WAIT = "wait"
    CLARIFY = "clarify"
    BLOCK = "block"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class RiskClass(str, Enum):
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
    ACTION_SELECTED = "action_selected"
    ACTION_UNCERTAINTY_TOO_HIGH = "action_uncertainty_too_high"
    COMMITTED_EFFECT_REQUIRES_RECONCILIATION = (
        "committed_effect_requires_reconciliation"
    )
    MISSING_OBSERVATIONS = "missing_observations"
    CONFLICTING_OBSERVATIONS = "conflicting_observations"
    STATE_NOT_FRESH = "state_not_fresh"
    LOW_PRECONDITION_CONFIDENCE = "low_precondition_confidence"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    NO_ACTION_CANDIDATE = "no_action_candidate"
    HUMAN_GATE_REQUIRED = "human_gate_required"
    BUDGET_EXCEEDED = "budget_exceeded"
    MUTATION_DISABLED = "mutation_disabled"
    OSCILLATION_COOLDOWN_ACTIVE = "oscillation_cooldown_active"
    STRATEGY_SWITCH_REQUIRED = "strategy_switch_required"
    NO_SAFE_ACTION = "no_safe_action"


class ConstraintStatus(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"
    REQUIRES_CLARIFY = "requires_clarify"
    WAITING = "waiting"
    SUPPRESSED = "suppressed"


class HorizonValidationStatus(str, Enum):
    VALIDATED = "validated"
    REJECTED = "rejected"
    ROLLBACK_REQUIRED = "rollback_required"


class HorizonValidationReason(str, Enum):
    LEADING_STEP_MATCHED = "leading_step_matched"
    ANCHOR_STATE_DIVERGED = "anchor_state_diverged"
    HORIZON_LIMIT_EXCEEDED = "horizon_limit_exceeded"
    EXECUTED_ACTION_DIVERGED = "executed_action_diverged"
    OBSERVED_STATE_DIVERGED = "observed_state_diverged"
    EFFECT_NOT_COMMITTED = "effect_not_committed"


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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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

    def active_constraints(self) -> tuple[str, ...]:
        constraints: list[str] = []
        if self.latency_ms is not None:
            constraints.append(f"budget.latency_ms<={self.latency_ms}")
        if self.tokens is not None:
            constraints.append(f"budget.tokens<={self.tokens}")
        if self.resource_units is not None:
            constraints.append(f"budget.resource_units<={self.resource_units}")
        return tuple(constraints)


@dataclass(frozen=True, slots=True)
class StateEstimate:
    """Explicit state boundary consumed by the policy."""

    freshness: Freshness = Freshness.UNKNOWN
    confidence: float | None = None
    missing_inputs: tuple[str, ...] = ()
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
            "missing_inputs",
            tuple(
                sorted(
                    {
                        _require_text(item, "missing_input")
                        for item in self.missing_inputs
                    }
                )
            ),
        )
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted({_require_text(item, "conflict") for item in self.conflicts})),
        )
        if not isinstance(self.capability_available, bool):
            raise TypeError("capability_available must be boolean")
        if not isinstance(self.effect_committed, bool):
            raise TypeError("effect_committed must be boolean")


@dataclass(frozen=True, slots=True)
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
        if not isinstance(self.mutating, bool):
            raise TypeError("mutating must be boolean")
        if not isinstance(self.irreversible, bool):
            raise TypeError("irreversible must be boolean")
        if not isinstance(self.requires_human_gate, bool):
            raise TypeError("requires_human_gate must be boolean")


@dataclass(frozen=True, slots=True)
class HorizonStep:
    """One predicted action boundary and its caller-owned rollback intent."""

    action_digest: str
    expected_state_digest: str
    rollback_action_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "action_digest",
            "expected_state_digest",
            "rollback_action_digest",
        ):
            object.__setattr__(
                self, field_name, _require_text(getattr(self, field_name), field_name)
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "action_digest": self.action_digest,
            "expected_state_digest": self.expected_state_digest,
            "rollback_action_digest": self.rollback_action_digest,
        }


@dataclass(frozen=True, slots=True)
class HorizonPlan:
    """A bounded prediction horizon; only its leading step may be validated."""

    anchor_state_digest: str
    steps: tuple[HorizonStep, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "anchor_state_digest",
            _require_text(self.anchor_state_digest, "anchor_state_digest"),
        )
        object.__setattr__(self, "steps", tuple(self.steps))
        if not self.steps:
            raise ValueError("steps must contain at least one horizon step")
        if not all(isinstance(step, HorizonStep) for step in self.steps):
            raise TypeError("steps must contain only HorizonStep values")

    def to_dict(self) -> dict[str, object]:
        return {
            "anchor_state_digest": self.anchor_state_digest,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True, slots=True)
class HorizonValidationReceipt:
    """Validation or rollback intent for the leading observation boundary."""

    status: HorizonValidationStatus
    reason: HorizonValidationReason
    anchor_state_digest: str
    observed_anchor_state_digest: str
    executed_action_digest: str
    expected_state_digest: str
    observed_state_digest: str
    rollback_action_digest: str
    horizon_steps: int
    validated_steps: int
    effect_committed: bool
    replan_required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.status, HorizonValidationStatus):
            object.__setattr__(self, "status", HorizonValidationStatus(self.status))
        if not isinstance(self.reason, HorizonValidationReason):
            object.__setattr__(self, "reason", HorizonValidationReason(self.reason))
        for field_name in (
            "anchor_state_digest",
            "observed_anchor_state_digest",
            "executed_action_digest",
            "expected_state_digest",
            "observed_state_digest",
            "rollback_action_digest",
        ):
            object.__setattr__(
                self, field_name, _require_text(getattr(self, field_name), field_name)
            )
        if not isinstance(self.horizon_steps, int) or isinstance(
            self.horizon_steps, bool
        ):
            raise TypeError("horizon_steps must be an integer")
        if self.horizon_steps < 1:
            raise ValueError("horizon_steps must be positive")
        if not isinstance(self.validated_steps, int) or isinstance(
            self.validated_steps, bool
        ):
            raise TypeError("validated_steps must be an integer")
        if self.validated_steps not in (0, 1):
            raise ValueError("validated_steps must be zero or one")
        if not isinstance(self.effect_committed, bool):
            raise TypeError("effect_committed must be boolean")
        if not isinstance(self.replan_required, bool):
            raise TypeError("replan_required must be boolean")
        validated = self.status is HorizonValidationStatus.VALIDATED
        if (
            self.validated_steps != int(validated)
            or self.replan_required is not validated
        ):
            raise ValueError(
                "validated status must record one step and require replanning"
            )
        if (
            validated != self.effect_committed
            and self.status is not HorizonValidationStatus.ROLLBACK_REQUIRED
        ):
            raise ValueError("receipt status must agree with committed effect state")
        if (
            self.status is HorizonValidationStatus.ROLLBACK_REQUIRED
            and not self.effect_committed
        ):
            raise ValueError("rollback_required needs a committed effect")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": HORIZON_SCHEMA_VERSION,
            "status": self.status.value,
            "reason": self.reason.value,
            "anchor_state_digest": self.anchor_state_digest,
            "observed_anchor_state_digest": self.observed_anchor_state_digest,
            "executed_action_digest": self.executed_action_digest,
            "expected_state_digest": self.expected_state_digest,
            "observed_state_digest": self.observed_state_digest,
            "rollback_action_digest": self.rollback_action_digest,
            "horizon_steps": self.horizon_steps,
            "validated_steps": self.validated_steps,
            "effect_committed": self.effect_committed,
            "replan_required": self.replan_required,
        }


@dataclass(frozen=True, slots=True)
class ConstraintReceipt:
    """Explicit policy or budget constraint evaluation."""

    constraint_id: str
    status: ConstraintStatus
    detail: str
    candidate_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "constraint_id", _require_text(self.constraint_id, "constraint_id")
        )
        if not isinstance(self.status, ConstraintStatus):
            object.__setattr__(self, "status", ConstraintStatus(self.status))
        object.__setattr__(self, "detail", _require_text(self.detail, "detail"))
        if self.candidate_digest:
            object.__setattr__(
                self,
                "candidate_digest",
                _require_text(self.candidate_digest, "candidate_digest"),
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "constraint_id": self.constraint_id,
            "status": self.status.value,
            "detail": self.detail,
            "candidate_digest": self.candidate_digest,
        }


@dataclass(frozen=True, slots=True)
class AntiOscillationState:
    """Recent failure fingerprint state shared by the caller."""

    fingerprint: str = ""
    repeated_failures: int = 0
    cooldown_remaining: int = 0
    last_action_digest: str = ""
    suppressed_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.fingerprint:
            object.__setattr__(
                self, "fingerprint", _require_text(self.fingerprint, "fingerprint")
            )
        if (
            not isinstance(self.repeated_failures, int)
            or isinstance(self.repeated_failures, bool)
            or self.repeated_failures < 0
        ):
            raise ValueError("repeated_failures must be a non-negative integer")
        if (
            not isinstance(self.cooldown_remaining, int)
            or isinstance(self.cooldown_remaining, bool)
            or self.cooldown_remaining < 0
        ):
            raise ValueError("cooldown_remaining must be a non-negative integer")
        if self.last_action_digest:
            object.__setattr__(
                self,
                "last_action_digest",
                _require_text(self.last_action_digest, "last_action_digest"),
            )
        object.__setattr__(
            self,
            "suppressed_actions",
            tuple(
                sorted(
                    {
                        _require_text(item, "suppressed_action")
                        for item in self.suppressed_actions
                    }
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class AntiOscillationReceipt:
    """Deterministic receipt for cooldown / hysteresis / strategy switching."""

    fingerprint: str
    repeated_failures: int
    retry_limit: int
    cooldown_remaining: int
    suppressed_actions: tuple[str, ...]
    strategy_switch_required: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fingerprint", _require_text(self.fingerprint, "fingerprint")
        )
        if (
            not isinstance(self.repeated_failures, int)
            or isinstance(self.repeated_failures, bool)
            or self.repeated_failures < 0
        ):
            raise ValueError("repeated_failures must be a non-negative integer")
        if (
            not isinstance(self.retry_limit, int)
            or isinstance(self.retry_limit, bool)
            or self.retry_limit < 1
        ):
            raise ValueError("retry_limit must be a positive integer")
        if (
            not isinstance(self.cooldown_remaining, int)
            or isinstance(self.cooldown_remaining, bool)
            or self.cooldown_remaining < 0
        ):
            raise ValueError("cooldown_remaining must be a non-negative integer")
        object.__setattr__(
            self,
            "suppressed_actions",
            tuple(
                sorted(
                    {
                        _require_text(item, "suppressed_action")
                        for item in self.suppressed_actions
                    }
                )
            ),
        )
        if not isinstance(self.strategy_switch_required, bool):
            raise TypeError("strategy_switch_required must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "repeated_failures": self.repeated_failures,
            "retry_limit": self.retry_limit,
            "cooldown_remaining": self.cooldown_remaining,
            "suppressed_actions": list(self.suppressed_actions),
            "strategy_switch_required": self.strategy_switch_required,
        }


_DEFAULT_HUMAN_GATED_RISKS = frozenset(
    {
        RiskClass.EXTERNAL_COMMUNICATION,
        RiskClass.PUBLISH,
        RiskClass.DELETE,
        RiskClass.PAYMENT,
        RiskClass.CREDENTIAL,
        RiskClass.PRIVILEGE_ESCALATION,
    }
)


@dataclass(frozen=True, slots=True)
class ControllerPolicy:
    """Versioned decision policy; no online tuning is performed here."""

    policy_version: str = CONTROLLER_SCHEMA_VERSION
    min_precondition_confidence: float = 0.8
    max_action_uncertainty: float = 0.5
    budget: ActionBudget = ActionBudget()
    allow_mutations: bool = True
    human_gated_risks: frozenset[RiskClass] = _DEFAULT_HUMAN_GATED_RISKS
    max_repeat_failures: int = 2
    max_horizon_steps: int = 3
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
            "max_action_uncertainty",
            _unit_interval(self.max_action_uncertainty, "max_action_uncertainty"),
        )
        object.__setattr__(
            self,
            "human_gated_risks",
            frozenset(
                risk if isinstance(risk, RiskClass) else RiskClass(risk)
                for risk in self.human_gated_risks
            ),
        )
        if (
            not isinstance(self.max_repeat_failures, int)
            or isinstance(self.max_repeat_failures, bool)
            or self.max_repeat_failures < 1
        ):
            raise ValueError("max_repeat_failures must be a positive integer")
        if (
            not isinstance(self.max_horizon_steps, int)
            or isinstance(self.max_horizon_steps, bool)
            or self.max_horizon_steps < 1
        ):
            raise ValueError("max_horizon_steps must be a positive integer")
        if not isinstance(self.allow_mutations, bool):
            raise TypeError("allow_mutations must be boolean")
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

    def active_constraints(self) -> tuple[str, ...]:
        return (
            f"policy.version={self.policy_version}",
            f"policy.min_precondition_confidence>={self.min_precondition_confidence}",
            f"policy.max_action_uncertainty<={self.max_action_uncertainty}",
            f"policy.allow_mutations={str(self.allow_mutations).lower()}",
            f"policy.max_repeat_failures={self.max_repeat_failures}",
            f"policy.max_horizon_steps={self.max_horizon_steps}",
            *self.budget.active_constraints(),
        )


@dataclass(frozen=True, slots=True)
class DecisionBase:
    kind: DecisionKind
    reason_code: ReasonCode
    policy_version: str
    alternatives_considered: tuple[str, ...] = ()
    active_constraints: tuple[str, ...] = ()
    constraint_receipts: tuple[ConstraintReceipt, ...] = ()
    anti_oscillation: AntiOscillationReceipt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DecisionKind):
            object.__setattr__(self, "kind", DecisionKind(self.kind))
        if not isinstance(self.reason_code, ReasonCode):
            object.__setattr__(self, "reason_code", ReasonCode(self.reason_code))
        object.__setattr__(
            self,
            "policy_version",
            _require_text(self.policy_version, "policy_version"),
        )
        object.__setattr__(
            self,
            "alternatives_considered",
            tuple(self.alternatives_considered),
        )
        object.__setattr__(self, "active_constraints", tuple(self.active_constraints))
        object.__setattr__(
            self, "constraint_receipts", tuple(self.constraint_receipts)
        )

    def _base_dict(self) -> dict[str, object]:
        return {
            "schema_version": CONTROLLER_SCHEMA_VERSION,
            "kind": self.kind.value,
            "reason_code": self.reason_code.value,
            "policy_version": self.policy_version,
            "alternatives_considered": list(self.alternatives_considered),
            "active_constraints": list(self.active_constraints),
            "constraint_receipts": [
                receipt.to_dict() for receipt in self.constraint_receipts
            ],
            "anti_oscillation": self.anti_oscillation.to_dict()
            if self.anti_oscillation
            else None,
        }

    def to_dict(self) -> dict[str, object]:
        return self._base_dict()

    def evidence_digest(self) -> str:
        """Return a stable identity for a decision receipt across replays."""

        return hashlib.sha256(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionDecision(DecisionBase):
    action_digest: str = ""
    predicted_effect: str = ""
    predicted_cost: ActionCost | None = None
    risk: RiskClass | None = None
    verifier: str = ""
    score: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "kind", DecisionKind.ACTION)
        object.__setattr__(
            self, "action_digest", _require_text(self.action_digest, "action_digest")
        )
        object.__setattr__(
            self,
            "predicted_effect",
            _require_text(self.predicted_effect, "predicted_effect"),
        )
        if not isinstance(self.predicted_cost, ActionCost):
            raise TypeError("predicted_cost must be an ActionCost")
        if not isinstance(self.risk, RiskClass):
            object.__setattr__(self, "risk", RiskClass(self.risk))
        object.__setattr__(self, "verifier", _require_text(self.verifier, "verifier"))
        if self.score is None or not math.isfinite(float(self.score)):
            raise ValueError("score must be finite")
        object.__setattr__(self, "score", float(self.score))

    def to_dict(self) -> dict[str, object]:
        payload = self._base_dict()
        payload.update(
            {
                "action_digest": self.action_digest,
                "predicted_effect": self.predicted_effect,
                "predicted_cost": self.predicted_cost.to_dict(),
                "risk": self.risk.value,
                "verifier": self.verifier,
                "score": self.score,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class ObserveDecision(DecisionBase):
    missing_inputs: tuple[str, ...] = ()
    conflicting_inputs: tuple[str, ...] = ()
    observation_request: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "kind", DecisionKind.OBSERVE)
        object.__setattr__(self, "missing_inputs", tuple(self.missing_inputs))
        object.__setattr__(self, "conflicting_inputs", tuple(self.conflicting_inputs))
        object.__setattr__(
            self,
            "observation_request",
            _require_text(self.observation_request, "observation_request"),
        )

    def to_dict(self) -> dict[str, object]:
        payload = self._base_dict()
        payload.update(
            {
                "missing_inputs": list(self.missing_inputs),
                "conflicting_inputs": list(self.conflicting_inputs),
                "observation_request": self.observation_request,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class WaitDecision(DecisionBase):
    wait_for: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "kind", DecisionKind.WAIT)
        object.__setattr__(self, "wait_for", _require_text(self.wait_for, "wait_for"))

    def to_dict(self) -> dict[str, object]:
        payload = self._base_dict()
        payload["wait_for"] = self.wait_for
        return payload


@dataclass(frozen=True, slots=True)
class ClarifyDecision(DecisionBase):
    action_digest: str = ""
    predicted_effect: str = ""
    predicted_cost: ActionCost | None = None
    risk: RiskClass | None = None
    verifier: str = ""
    clarify_prompt: str = ""
    score: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "kind", DecisionKind.CLARIFY)
        object.__setattr__(
            self, "action_digest", _require_text(self.action_digest, "action_digest")
        )
        object.__setattr__(
            self,
            "predicted_effect",
            _require_text(self.predicted_effect, "predicted_effect"),
        )
        if not isinstance(self.predicted_cost, ActionCost):
            raise TypeError("predicted_cost must be an ActionCost")
        if not isinstance(self.risk, RiskClass):
            object.__setattr__(self, "risk", RiskClass(self.risk))
        object.__setattr__(self, "verifier", _require_text(self.verifier, "verifier"))
        object.__setattr__(
            self,
            "clarify_prompt",
            _require_text(self.clarify_prompt, "clarify_prompt"),
        )
        if self.score is None or not math.isfinite(float(self.score)):
            raise ValueError("score must be finite")
        object.__setattr__(self, "score", float(self.score))

    def to_dict(self) -> dict[str, object]:
        payload = self._base_dict()
        payload.update(
            {
                "action_digest": self.action_digest,
                "predicted_effect": self.predicted_effect,
                "predicted_cost": self.predicted_cost.to_dict(),
                "risk": self.risk.value,
                "verifier": self.verifier,
                "clarify_prompt": self.clarify_prompt,
                "score": self.score,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class BlockDecision(DecisionBase):
    blocked_by: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "kind", DecisionKind.BLOCK)
        object.__setattr__(
            self, "blocked_by", _require_text(self.blocked_by, "blocked_by")
        )

    def to_dict(self) -> dict[str, object]:
        payload = self._base_dict()
        payload["blocked_by"] = self.blocked_by
        return payload


ControllerDecision = (
    ActionDecision | ObserveDecision | WaitDecision | ClarifyDecision | BlockDecision
)


class ClosedLoopController:
    """Pure policy evaluator; callers own execution, observation, and replay."""

    def __init__(self, policy: ControllerPolicy | None = None) -> None:
        self.policy = policy or ControllerPolicy()

    def validate_horizon(
        self,
        plan: HorizonPlan,
        *,
        observed_anchor_state_digest: str,
        executed_action_digest: str,
        observed_state_digest: str,
        effect_committed: bool,
    ) -> HorizonValidationReceipt:
        """Validate one leading step and return a caller-owned rollback intent."""

        if not isinstance(plan, HorizonPlan):
            raise TypeError("plan must be a HorizonPlan")
        observed_anchor_state_digest = _require_text(
            observed_anchor_state_digest, "observed_anchor_state_digest"
        )
        executed_action_digest = _require_text(
            executed_action_digest, "executed_action_digest"
        )
        observed_state_digest = _require_text(
            observed_state_digest, "observed_state_digest"
        )
        if not isinstance(effect_committed, bool):
            raise TypeError("effect_committed must be boolean")

        leading = plan.steps[0]
        if observed_anchor_state_digest != plan.anchor_state_digest:
            reason = HorizonValidationReason.ANCHOR_STATE_DIVERGED
        elif len(plan.steps) > self.policy.max_horizon_steps:
            reason = HorizonValidationReason.HORIZON_LIMIT_EXCEEDED
        elif executed_action_digest != leading.action_digest:
            reason = HorizonValidationReason.EXECUTED_ACTION_DIVERGED
        elif observed_state_digest != leading.expected_state_digest:
            reason = HorizonValidationReason.OBSERVED_STATE_DIVERGED
        elif not effect_committed:
            reason = HorizonValidationReason.EFFECT_NOT_COMMITTED
        else:
            reason = HorizonValidationReason.LEADING_STEP_MATCHED

        if reason is HorizonValidationReason.LEADING_STEP_MATCHED:
            status = HorizonValidationStatus.VALIDATED
        elif effect_committed:
            status = HorizonValidationStatus.ROLLBACK_REQUIRED
        else:
            status = HorizonValidationStatus.REJECTED

        return HorizonValidationReceipt(
            status=status,
            reason=reason,
            anchor_state_digest=plan.anchor_state_digest,
            observed_anchor_state_digest=observed_anchor_state_digest,
            executed_action_digest=executed_action_digest,
            expected_state_digest=leading.expected_state_digest,
            observed_state_digest=observed_state_digest,
            rollback_action_digest=leading.rollback_action_digest,
            horizon_steps=len(plan.steps),
            validated_steps=int(status is HorizonValidationStatus.VALIDATED),
            effect_committed=effect_committed,
            replan_required=status is HorizonValidationStatus.VALIDATED,
        )

    def decide(
        self,
        goal: str,
        state: StateEstimate,
        candidates: Iterable[ActionCandidate],
        *,
        anti_oscillation: AntiOscillationState | None = None,
    ) -> ControllerDecision:
        """Select one bounded step, or fail closed with an explicit contract."""

        _require_text(goal, "goal")
        if not isinstance(state, StateEstimate):
            raise TypeError("state must be a StateEstimate")
        anti_oscillation = anti_oscillation or AntiOscillationState()
        ordered = tuple(sorted(candidates, key=lambda item: item.action_digest))
        alternatives = tuple(item.action_digest for item in ordered)
        active_constraints = self.policy.active_constraints()
        base_receipts: list[ConstraintReceipt] = []

        if state.effect_committed:
            return ObserveDecision(
                kind=DecisionKind.OBSERVE,
                reason_code=ReasonCode.COMMITTED_EFFECT_REQUIRES_RECONCILIATION,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=(
                    ConstraintReceipt(
                        "effect.reconciliation",
                        ConstraintStatus.WAITING,
                        "committed effect must be reconciled before retry",
                    ),
                ),
                observation_request="reconcile_committed_effect",
            )
        if state.missing_inputs:
            return ObserveDecision(
                kind=DecisionKind.OBSERVE,
                reason_code=ReasonCode.MISSING_OBSERVATIONS,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=(
                    ConstraintReceipt(
                        "state.missing_inputs",
                        ConstraintStatus.WAITING,
                        "missing state inputs prevent a bounded mutation",
                    ),
                ),
                missing_inputs=state.missing_inputs,
                observation_request="collect_missing_inputs",
            )
        if state.conflicts:
            return ObserveDecision(
                kind=DecisionKind.OBSERVE,
                reason_code=ReasonCode.CONFLICTING_OBSERVATIONS,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=(
                    ConstraintReceipt(
                        "state.conflicts",
                        ConstraintStatus.WAITING,
                        "conflicting observations require re-anchoring",
                    ),
                ),
                conflicting_inputs=state.conflicts,
                observation_request="resolve_conflicting_inputs",
            )
        if state.freshness is not Freshness.FRESH:
            return ObserveDecision(
                kind=DecisionKind.OBSERVE,
                reason_code=ReasonCode.STATE_NOT_FRESH,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=(
                    ConstraintReceipt(
                        "state.freshness",
                        ConstraintStatus.WAITING,
                        f"state freshness is {state.freshness.value}",
                    ),
                ),
                observation_request="refresh_state_boundary",
            )
        if (
            state.confidence is None
            or state.confidence < self.policy.min_precondition_confidence
        ):
            return ObserveDecision(
                kind=DecisionKind.OBSERVE,
                reason_code=ReasonCode.LOW_PRECONDITION_CONFIDENCE,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=(
                    ConstraintReceipt(
                        "state.precondition_confidence",
                        ConstraintStatus.WAITING,
                        "precondition confidence is below policy threshold",
                    ),
                ),
                observation_request="improve_precondition_confidence",
            )
        if not state.capability_available:
            return WaitDecision(
                kind=DecisionKind.WAIT,
                reason_code=ReasonCode.CAPABILITY_UNAVAILABLE,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=(
                    ConstraintReceipt(
                        "capability.available",
                        ConstraintStatus.WAITING,
                        "required capability is unavailable or unhealthy",
                    ),
                ),
                wait_for="capability_health",
            )
        if not ordered:
            return ObserveDecision(
                kind=DecisionKind.OBSERVE,
                reason_code=ReasonCode.NO_ACTION_CANDIDATE,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=(
                    ConstraintReceipt(
                        "candidate.available",
                        ConstraintStatus.WAITING,
                        "no candidate actions were supplied",
                    ),
                ),
                observation_request="enumerate_candidates",
            )

        oscillation_receipt = self._anti_oscillation_receipt(anti_oscillation)
        suppressed = set(anti_oscillation.suppressed_actions)
        if (
            anti_oscillation.repeated_failures >= self.policy.max_repeat_failures
            and anti_oscillation.last_action_digest
        ):
            suppressed.add(anti_oscillation.last_action_digest)

        safe: list[ActionCandidate] = []
        gated: list[ActionCandidate] = []
        budget_blocked: list[ConstraintReceipt] = []
        mutation_blocked: list[ConstraintReceipt] = []
        suppressed_receipts: list[ConstraintReceipt] = []
        uncertainty_blocked: list[ConstraintReceipt] = []

        for candidate in ordered:
            exceeded = self.policy.budget.exceeded(candidate.cost)
            if exceeded:
                budget_blocked.append(
                    ConstraintReceipt(
                        "budget",
                        ConstraintStatus.BLOCKED,
                        f"candidate exceeds {','.join(exceeded)} budget",
                        candidate.action_digest,
                    )
                )
                continue
            if candidate.mutating and not self.policy.allow_mutations:
                mutation_blocked.append(
                    ConstraintReceipt(
                        "policy.allow_mutations",
                        ConstraintStatus.BLOCKED,
                        "mutating candidate is disabled by policy",
                        candidate.action_digest,
                    )
                )
                continue
            if candidate.action_digest in suppressed:
                suppressed_receipts.append(
                    ConstraintReceipt(
                        "anti_oscillation",
                        ConstraintStatus.SUPPRESSED,
                        "candidate suppressed after repeated failure fingerprint",
                        candidate.action_digest,
                    )
                )
                continue
            if candidate.uncertainty > self.policy.max_action_uncertainty:
                uncertainty_blocked.append(
                    ConstraintReceipt(
                        "candidate.uncertainty",
                        ConstraintStatus.WAITING,
                        "candidate uncertainty exceeds action threshold",
                        candidate.action_digest,
                    )
                )
                continue
            requires_gate = (
                candidate.requires_human_gate
                or candidate.risk in self.policy.human_gated_risks
                or candidate.irreversible
                or candidate.cost.irreversibility > 0.0
            )
            if requires_gate:
                gated.append(candidate)
                base_receipts.append(
                    ConstraintReceipt(
                        "human_gate",
                        ConstraintStatus.REQUIRES_CLARIFY,
                        "candidate requires a human gate before execution",
                        candidate.action_digest,
                    )
                )
            else:
                safe.append(candidate)
                base_receipts.append(
                    ConstraintReceipt(
                        "candidate.eligible",
                        ConstraintStatus.PASSED,
                        "candidate satisfies current policy constraints",
                        candidate.action_digest,
                    )
                )

        if safe:
            selected = min(
                safe, key=lambda item: (self.policy.score(item), item.action_digest)
            )
            return ActionDecision(
                kind=DecisionKind.ACTION,
                reason_code=ReasonCode.ACTION_SELECTED,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=tuple(
                    base_receipts
                    + budget_blocked
                    + mutation_blocked
                    + suppressed_receipts
                    + uncertainty_blocked
                ),
                anti_oscillation=oscillation_receipt,
                action_digest=selected.action_digest,
                predicted_effect=selected.predicted_effect,
                predicted_cost=selected.cost,
                risk=selected.risk,
                verifier=selected.verifier,
                score=self.policy.score(selected),
            )
        if gated:
            selected = min(
                gated, key=lambda item: (self.policy.score(item), item.action_digest)
            )
            return ClarifyDecision(
                kind=DecisionKind.CLARIFY,
                reason_code=ReasonCode.HUMAN_GATE_REQUIRED,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=tuple(
                    base_receipts
                    + budget_blocked
                    + mutation_blocked
                    + suppressed_receipts
                    + uncertainty_blocked
                ),
                anti_oscillation=oscillation_receipt,
                action_digest=selected.action_digest,
                predicted_effect=selected.predicted_effect,
                predicted_cost=selected.cost,
                risk=selected.risk,
                verifier=selected.verifier,
                clarify_prompt="human gate required before high-risk or irreversible action",
                score=self.policy.score(selected),
            )
        if uncertainty_blocked:
            return ObserveDecision(
                kind=DecisionKind.OBSERVE,
                reason_code=ReasonCode.ACTION_UNCERTAINTY_TOO_HIGH,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=tuple(
                    uncertainty_blocked
                    + budget_blocked
                    + mutation_blocked
                    + suppressed_receipts
                ),
                anti_oscillation=oscillation_receipt,
                observation_request="reduce_action_uncertainty",
            )
        if (
            oscillation_receipt is not None
            and oscillation_receipt.cooldown_remaining > 0
            and suppressed
        ):
            return WaitDecision(
                kind=DecisionKind.WAIT,
                reason_code=ReasonCode.OSCILLATION_COOLDOWN_ACTIVE,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=tuple(suppressed_receipts),
                anti_oscillation=oscillation_receipt,
                wait_for="anti_oscillation_cooldown",
            )
        if oscillation_receipt is not None and oscillation_receipt.strategy_switch_required:
            return BlockDecision(
                kind=DecisionKind.BLOCK,
                reason_code=ReasonCode.STRATEGY_SWITCH_REQUIRED,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=tuple(
                    suppressed_receipts + budget_blocked + mutation_blocked
                ),
                anti_oscillation=oscillation_receipt,
                blocked_by="anti_oscillation",
            )
        if budget_blocked:
            return BlockDecision(
                kind=DecisionKind.BLOCK,
                reason_code=ReasonCode.BUDGET_EXCEEDED,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=tuple(budget_blocked),
                anti_oscillation=oscillation_receipt,
                blocked_by="budget",
            )
        if mutation_blocked:
            return BlockDecision(
                kind=DecisionKind.BLOCK,
                reason_code=ReasonCode.MUTATION_DISABLED,
                policy_version=self.policy.policy_version,
                alternatives_considered=alternatives,
                active_constraints=active_constraints,
                constraint_receipts=tuple(mutation_blocked),
                anti_oscillation=oscillation_receipt,
                blocked_by="mutation_policy",
            )
        return BlockDecision(
            kind=DecisionKind.BLOCK,
            reason_code=ReasonCode.NO_SAFE_ACTION,
            policy_version=self.policy.policy_version,
            alternatives_considered=alternatives,
            active_constraints=active_constraints,
            constraint_receipts=tuple(base_receipts + suppressed_receipts),
            anti_oscillation=oscillation_receipt,
            blocked_by="no_safe_candidate",
        )

    def _anti_oscillation_receipt(
        self, state: AntiOscillationState
    ) -> AntiOscillationReceipt | None:
        if not state.fingerprint:
            return None
        strategy_switch_required = (
            state.repeated_failures >= self.policy.max_repeat_failures
            and state.cooldown_remaining == 0
        )
        suppressed = state.suppressed_actions
        if (
            state.repeated_failures >= self.policy.max_repeat_failures
            and state.last_action_digest
        ):
            suppressed = tuple(sorted({*suppressed, state.last_action_digest}))
        return AntiOscillationReceipt(
            fingerprint=state.fingerprint,
            repeated_failures=state.repeated_failures,
            retry_limit=self.policy.max_repeat_failures,
            cooldown_remaining=state.cooldown_remaining,
            suppressed_actions=suppressed,
            strategy_switch_required=strategy_switch_required,
        )


__all__ = [
    "CONTROLLER_SCHEMA_VERSION",
    "ActionBudget",
    "ActionCandidate",
    "ActionCost",
    "ActionDecision",
    "AntiOscillationReceipt",
    "AntiOscillationState",
    "BlockDecision",
    "ClarifyDecision",
    "ClosedLoopController",
    "ConstraintReceipt",
    "ConstraintStatus",
    "ControllerDecision",
    "ControllerPolicy",
    "DecisionBase",
    "DecisionKind",
    "Freshness",
    "HORIZON_SCHEMA_VERSION",
    "HorizonPlan",
    "HorizonStep",
    "HorizonValidationReason",
    "HorizonValidationReceipt",
    "HorizonValidationStatus",
    "ObserveDecision",
    "ReasonCode",
    "RiskClass",
    "StateEstimate",
    "WaitDecision",
]
