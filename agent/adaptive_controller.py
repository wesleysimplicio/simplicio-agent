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


ADAPTIVE_CONTROLLER_SCHEMA = "simplicio.adaptive-controller/v1"


class ControllerAction(StrEnum):
    HOLD = "hold"
    THROTTLE = "throttle"
    DECAY = "decay"
    SCALE_UP = "scale_up"


def _ratio(value: float, name: str) -> float:
    value = float(value)
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

    def __post_init__(self) -> None:
        if isinstance(self.min_concurrency, bool) or self.min_concurrency < 0:
            raise ValueError("min_concurrency must be >= 0")
        if isinstance(self.max_concurrency, bool) or self.max_concurrency < self.min_concurrency:
            raise ValueError("max_concurrency must be >= min_concurrency")
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
        if self.integral_limit < 0 or not math.isfinite(float(self.integral_limit)):
            raise ValueError("integral_limit must be finite and >= 0")
        for name in ("proportional_gain", "integral_gain", "derivative_gain"):
            value = float(getattr(self, name))
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
        if isinstance(self.current_concurrency, bool) or self.current_concurrency < 0:
            raise ValueError("current_concurrency must be >= 0")


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

    def to_dict(self) -> dict[str, object]:
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
        }


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
            action = ControllerAction.THROTTLE if target < current else ControllerAction.HOLD
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
            target = min(self.policy.max_concurrency, max(current + 1, current * 2))
            action = ControllerAction.SCALE_UP
            reason = "bounded_scale_up"
        else:
            target = current
            action = ControllerAction.HOLD
            reason = "within_bounds"

        next_state = AdaptiveState(pressure_active, integral, error)
        return AdaptiveDecision(target, action, pressure_active, pid_output, reason, next_state)


__all__ = [
    "ADAPTIVE_CONTROLLER_SCHEMA",
    "AdaptiveController",
    "AdaptiveDecision",
    "AdaptiveObservation",
    "AdaptivePolicy",
    "AdaptiveState",
    "ControllerAction",
]
