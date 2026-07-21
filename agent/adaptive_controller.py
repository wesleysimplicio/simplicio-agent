"""Deterministic, bounded adaptive concurrency policy for issue #320.

The controller is intentionally pure: it consumes one observation and prior
state, then returns one bounded target.  It does not schedule workers or
measure production latency.  Pressure wins over scale-up, hysteresis prevents
flapping, and marginal gain is required before fan-out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Sequence, TypeVar


ADAPTIVE_CONTROLLER_SCHEMA = "simplicio.adaptive-controller/v1"
ADAPTIVE_RECEIPT_SCHEMA = "simplicio.adaptive-controller-receipt/v1"


class ControllerAction(StrEnum):
    HOLD = "hold"
    THROTTLE = "throttle"
    DECAY = "decay"
    SCALE_UP = "scale_up"


def _ratio(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number between 0 and 1") from None
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return value


@dataclass(frozen=True, slots=True)
class AdaptivePolicy:
    min_concurrency: int = 0
    max_concurrency: int = 8
    pressure_enter: float = 0.8
    pressure_exit: float = 0.6
    queue_scale_threshold: float = 0.5
    entropy_scale_threshold: float = 0.5
    minimum_marginal_gain: float = 0.1
    integral_limit: float = 2.0
    proportional_gain: float = 1.0
    integral_gain: float = 0.1
    derivative_gain: float = 0.0
    max_fan_out: int | None = None

    def __post_init__(self) -> None:
        for name in ("min_concurrency", "max_concurrency"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.max_concurrency < self.min_concurrency:
            raise ValueError("max_concurrency must be >= min_concurrency")
        if self.max_fan_out is None:
            object.__setattr__(self, "max_fan_out", self.max_concurrency)
        elif (
            isinstance(self.max_fan_out, bool)
            or not isinstance(self.max_fan_out, int)
            or self.max_fan_out < 0
        ):
            raise ValueError("max_fan_out must be an integer >= 0")
        for name in (
            "pressure_enter",
            "pressure_exit",
            "queue_scale_threshold",
            "entropy_scale_threshold",
            "minimum_marginal_gain",
        ):
            object.__setattr__(self, name, _ratio(getattr(self, name), name))
        if self.pressure_exit > self.pressure_enter:
            raise ValueError("pressure_exit must be <= pressure_enter")
        if isinstance(self.integral_limit, bool):
            raise ValueError("integral_limit must be finite and >= 0")
        try:
            integral_limit = float(self.integral_limit)
        except (TypeError, ValueError):
            raise ValueError("integral_limit must be finite and >= 0") from None
        if integral_limit < 0 or not math.isfinite(integral_limit):
            raise ValueError("integral_limit must be finite and >= 0")
        object.__setattr__(self, "integral_limit", integral_limit)
        for name in ("proportional_gain", "integral_gain", "derivative_gain"):
            raw_value = getattr(self, name)
            if isinstance(raw_value, bool):
                raise ValueError(f"{name} must be finite and >= 0")
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be finite and >= 0") from None
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and >= 0")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class AdaptiveObservation:
    queue_pressure: float
    cpu_pressure: float
    memory_pressure: float
    working_set_entropy: float
    marginal_gain: float
    current_concurrency: int

    def __post_init__(self) -> None:
        for name in (
            "queue_pressure",
            "cpu_pressure",
            "memory_pressure",
            "working_set_entropy",
            "marginal_gain",
        ):
            object.__setattr__(self, name, _ratio(getattr(self, name), name))
        if (
            isinstance(self.current_concurrency, bool)
            or not isinstance(self.current_concurrency, int)
            or self.current_concurrency < 0
        ):
            raise ValueError("current_concurrency must be an integer >= 0")


@dataclass(frozen=True, slots=True)
class AdaptiveState:
    pressure_active: bool = False
    integral_error: float = 0.0
    previous_error: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.pressure_active, bool):
            raise TypeError("pressure_active must be bool")
        for name in ("integral_error", "previous_error"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class AdaptiveDecision:
    target_concurrency: int
    action: ControllerAction
    pressure_active: bool
    pid_output: float
    reason: str
    state: AdaptiveState
    receipt: "AdaptiveReceipt | None" = None

    def to_dict(self) -> dict[str, object]:
        receipt = self.receipt or AdaptiveReceipt(
            action=self.action,
            reason=self.reason,
            current_concurrency=self.target_concurrency,
            target_concurrency=self.target_concurrency,
            pressure_active=self.pressure_active,
            pid_output=self.pid_output,
        )
        return {
            "schema": ADAPTIVE_CONTROLLER_SCHEMA,
            "target_concurrency": self.target_concurrency,
            "action": self.action.value,
            "pressure_active": self.pressure_active,
            "pid_output": self.pid_output,
            "reason": self.reason,
            "state": {
                "pressure_active": self.state.pressure_active,
                "integral_error": self.state.integral_error,
                "previous_error": self.state.previous_error,
            },
            "receipt": receipt.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AdaptiveReceipt:
    """Safe, deterministic evidence for one policy evaluation.

    The receipt contains only normalized metrics and decision metadata.  It
    intentionally does not include context payloads, prompts, task names, or
    process identifiers, so callers can persist it on an existing ledger.
    """

    action: ControllerAction
    reason: str
    current_concurrency: int
    target_concurrency: int
    pressure_active: bool
    pid_output: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ADAPTIVE_RECEIPT_SCHEMA,
            "action": self.action.value,
            "reason": self.reason,
            "current_concurrency": self.current_concurrency,
            "target_concurrency": self.target_concurrency,
            "pressure_active": self.pressure_active,
            "pid_output": self.pid_output,
        }


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class FanOutReceipt:
    """Evidence for a bounded, deterministic fan-out selection."""

    requested: int
    allowed: int
    selected: int
    truncated: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ADAPTIVE_RECEIPT_SCHEMA,
            "kind": "fan_out",
            "requested": self.requested,
            "allowed": self.allowed,
            "selected": self.selected,
            "truncated": self.truncated,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class FanOutPlan(Generic[T]):
    """Stable input-order selection for an existing dispatch interface."""

    items: tuple[T, ...]
    receipt: FanOutReceipt

    def to_dict(self) -> dict[str, object]:
        # Do not serialize arbitrary task/context values; the receipt is the
        # wire-safe portion and callers retain ``items`` for dispatch.
        return {"items": len(self.items), "receipt": self.receipt.to_dict()}


class AdaptiveController:
    """Choose one bounded concurrency change from one observation."""

    def __init__(self, policy: AdaptivePolicy | None = None) -> None:
        self.policy = policy or AdaptivePolicy()

    def decide(
        self, observation: AdaptiveObservation, state: AdaptiveState | None = None
    ) -> AdaptiveDecision:
        if not isinstance(observation, AdaptiveObservation):
            raise TypeError("observation must be an AdaptiveObservation")
        state = state or AdaptiveState()
        resource_pressure = max(observation.cpu_pressure, observation.memory_pressure)
        pressure_active = (
            resource_pressure >= self.policy.pressure_exit
            if state.pressure_active
            else resource_pressure >= self.policy.pressure_enter
        )
        error = resource_pressure - self.policy.pressure_exit
        integral = max(
            -self.policy.integral_limit,
            min(self.policy.integral_limit, state.integral_error + error),
        )
        derivative = error - state.previous_error
        pid_output = (
            self.policy.proportional_gain * error
            + self.policy.integral_gain * integral
            + self.policy.derivative_gain * derivative
        )
        current = min(
            self.policy.max_concurrency,
            max(self.policy.min_concurrency, observation.current_concurrency),
        )

        if pressure_active:
            target = max(self.policy.min_concurrency, current - 1)
            action = (
                ControllerAction.THROTTLE if target < current else ControllerAction.HOLD
            )
            reason = "resource_pressure"
        elif (
            current > self.policy.min_concurrency
            and observation.queue_pressure < self.policy.queue_scale_threshold
            and observation.marginal_gain < self.policy.minimum_marginal_gain
        ):
            target = current - 1
            action = ControllerAction.DECAY
            reason = "insufficient_marginal_gain"
        elif (
            current < self.policy.max_concurrency
            and observation.queue_pressure >= self.policy.queue_scale_threshold
            and observation.working_set_entropy >= self.policy.entropy_scale_threshold
            and observation.marginal_gain >= self.policy.minimum_marginal_gain
        ):
            # Minimal action is deliberate: one observation can authorize one
            # additional worker only.  A later observation must authorize the
            # next step, preventing bursty fan-out and PID overshoot.
            target = current + 1
            action = ControllerAction.SCALE_UP
            reason = "bounded_scale_up"
        else:
            target = current
            action = ControllerAction.HOLD
            reason = "within_bounds"

        next_state = AdaptiveState(pressure_active, integral, error)
        receipt = AdaptiveReceipt(
            action=action,
            reason=reason,
            current_concurrency=current,
            target_concurrency=target,
            pressure_active=pressure_active,
            pid_output=pid_output,
        )
        return AdaptiveDecision(
            target, action, pressure_active, pid_output, reason, next_state, receipt
        )

    def bound_fan_out(
        self,
        items: Sequence[T],
        *,
        decision: AdaptiveDecision | None = None,
    ) -> FanOutPlan[T]:
        """Select at most the policy/decision limit in stable input order.

        This is a planning helper, not a dispatcher.  The returned tuple can
        be passed to existing synchronous or asynchronous batch interfaces;
        no worker, thread, or process is created here.
        """

        if isinstance(items, (str, bytes, bytearray)):
            raise TypeError("fan-out items must be a sequence of work items")
        if decision is not None and not isinstance(decision, AdaptiveDecision):
            raise TypeError("decision must be an AdaptiveDecision")
        requested = len(items)
        policy_limit = min(self.policy.max_fan_out or 0, self.policy.max_concurrency)
        decision_limit = (
            decision.target_concurrency if decision is not None else policy_limit
        )
        allowed = min(policy_limit, max(0, decision_limit))
        selected = tuple(items[:allowed])
        truncated = len(selected) < requested
        reason = "bounded_to_limit" if truncated else "within_limit"
        return FanOutPlan(
            items=selected,
            receipt=FanOutReceipt(
                requested=requested,
                allowed=allowed,
                selected=len(selected),
                truncated=truncated,
                reason=reason,
            ),
        )

    # Alias named after the policy operation used by callers that already
    # speak in terms of planning rather than bounding.
    plan_fan_out = bound_fan_out

    def evaluate_proposal(
        self,
        proposal: "AdaptiveProposal",
        *,
        existing_fingerprints: Sequence[str] = (),
    ) -> "ProposalGateReceipt":
        """Evaluate a topology proposal without executing or mutating it.

        Proposal validation remains on this existing controller boundary.  A
        caller owns issue/RFC creation and Runtime execution; this method only
        returns the receipt-backed gate outcome.
        """

        from agent.adaptive_architecture import evaluate_proposal_gate

        return evaluate_proposal_gate(
            proposal, existing_fingerprints=existing_fingerprints
        )


__all__ = [
    "ADAPTIVE_CONTROLLER_SCHEMA",
    "ADAPTIVE_RECEIPT_SCHEMA",
    "AdaptiveController",
    "AdaptiveDecision",
    "AdaptiveObservation",
    "AdaptivePolicy",
    "AdaptiveReceipt",
    "AdaptiveState",
    "ControllerAction",
    "FanOutPlan",
    "FanOutReceipt",
]

# Keep the existing controller as the public integration point while the
# passive proposal contract lives in its own focused module.
from agent.adaptive_architecture import (  # noqa: E402  (intentional re-export)
    AdaptiveProposal,
    ChangeType,
    EvidenceKind,
    EVIDENCE_SCHEMA,
    GATE_SCHEMA,
    GateCheck,
    ProposalEvidence,
    ProposalGateReceipt,
    ProposalRisk,
    PROPOSAL_SCHEMA,
    SemanticChange,
    Surface,
    Verdict,
    evaluate_proposal_gate,
)

__all__ += [
    "AdaptiveProposal",
    "ChangeType",
    "EvidenceKind",
    "EVIDENCE_SCHEMA",
    "GATE_SCHEMA",
    "GateCheck",
    "ProposalEvidence",
    "ProposalGateReceipt",
    "ProposalRisk",
    "PROPOSAL_SCHEMA",
    "SemanticChange",
    "Surface",
    "Verdict",
    "evaluate_proposal_gate",
]
