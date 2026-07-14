"""Pure, bounded adaptive fan-out governor contract.

The governor is deliberately an additive decision core.  It estimates useful
parallelism with Amdahl, estimates the work-in-progress target with Little's
law, and applies a bounded discrete PID correction.  It returns a stable
receipt instead of spawning workers or changing any scheduler/runtime state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from math import ceil, isfinite
from numbers import Real
from types import MappingProxyType
from typing import Any, Mapping


class FanoutReasonCode(StrEnum):
    """Machine-readable explanations for a fan-out decision."""

    INVALID_METRICS = "invalid_metrics"
    SERIAL_WORK = "serial_work"
    AMDAHL_LIMIT = "amdahl_limit"
    LITTLE_TARGET = "little_target"
    PID_INCREASE = "pid_increase"
    PID_DECREASE = "pid_decrease"
    HYSTERESIS = "hysteresis"
    PRESSURE_GUARD = "pressure_guard"
    FAILURE_GUARD = "failure_guard"
    ADDITIVE_STEP = "additive_step"
    LOWER_BOUND = "lower_bound"
    UPPER_BOUND = "upper_bound"
    HOLD = "hold"


@dataclass(frozen=True)
class FanoutMetrics:
    """Metrics supplied by an observation point; never mutated by the governor.

    Values are intentionally not validated in ``__post_init__``.  Metrics are
    runtime data and can be malformed; the decision function must fail closed
    with a safe minimum rather than raise or fan out.
    """

    queue_depth: Any = 0.0
    arrival_rate_per_second: Any = 0.0
    service_time_seconds: Any = 1.0
    parallel_fraction: Any = 1.0
    overhead_per_worker_seconds: Any = 0.0
    cpu_pressure: Any = 0.0
    memory_pressure: Any = 0.0
    io_pressure: Any = 0.0
    failure_rate: Any = 0.0
    observed_wait_seconds: Any = 0.0
    current_workers: Any = 1

    def validation_errors(self) -> tuple[str, ...]:
        """Return deterministic validation errors without raising."""

        errors: list[str] = []
        for name in (
            "queue_depth",
            "arrival_rate_per_second",
            "overhead_per_worker_seconds",
            "observed_wait_seconds",
        ):
            if not _valid_number(getattr(self, name), minimum=0.0):
                errors.append(name)
        if not _valid_number(self.service_time_seconds, minimum=0.0, strict_positive=True):
            errors.append("service_time_seconds")
        if not _valid_number(self.parallel_fraction, minimum=0.0, maximum=1.0):
            errors.append("parallel_fraction")
        for name in ("cpu_pressure", "memory_pressure", "io_pressure", "failure_rate"):
            if not _valid_number(getattr(self, name), minimum=0.0, maximum=1.0):
                errors.append(name)
        if not _valid_integer(self.current_workers, minimum=1):
            errors.append("current_workers")
        return tuple(errors)

    def safe_dict(self) -> dict[str, object]:
        """Return JSON-safe input data, including malformed values."""

        return {name: _safe_value(value) for name, value in asdict(self).items()}


@dataclass(frozen=True)
class FanoutGovernorConfig:
    """Ceilings and gains for one bounded governor policy."""

    min_workers: int = 1
    max_workers: int = 32
    max_step_up: int = 1
    max_step_down: int = 1
    target_wait_seconds: float = 1.0
    pid_kp: float = 1.0
    pid_ki: float = 0.1
    pid_kd: float = 0.05
    integral_limit: float = 10.0
    derivative_filter: float = 0.5
    hysteresis_workers: float = 0.25
    pressure_limit: float = 0.85
    failure_rate_limit: float = 0.20

    def __post_init__(self) -> None:
        if not _valid_integer(self.min_workers, minimum=1):
            raise ValueError("min_workers must be a positive integer")
        if not _valid_integer(self.max_workers, minimum=self.min_workers):
            raise ValueError("max_workers must be an integer >= min_workers")
        for name in ("max_step_up", "max_step_down"):
            if not _valid_integer(getattr(self, name), minimum=1):
                raise ValueError(f"{name} must be a positive integer")
        for name in ("target_wait_seconds", "integral_limit"):
            if not _valid_number(getattr(self, name), minimum=0.0, strict_positive=True):
                raise ValueError(f"{name} must be finite and positive")
        for name in ("pid_kp", "pid_ki", "pid_kd"):
            if not _valid_number(getattr(self, name), minimum=0.0):
                raise ValueError(f"{name} must be finite and non-negative")
        if not _valid_number(self.derivative_filter, minimum=0.0, maximum=1.0):
            raise ValueError("derivative_filter must be between 0 and 1")
        if not _valid_number(self.hysteresis_workers, minimum=0.0):
            raise ValueError("hysteresis_workers must be finite and non-negative")
        for name in ("pressure_limit", "failure_rate_limit"):
            if not _valid_number(getattr(self, name), minimum=0.0, maximum=1.0):
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class GovernorState:
    """Minimal state carried between observations."""

    current_workers: int = 1
    integral_error: float = 0.0
    previous_error: float | None = None
    filtered_derivative: float = 0.0


@dataclass(frozen=True)
class AmdahlEstimate:
    """Amdahl speedup and the largest useful worker count."""

    useful_workers: int
    speedup: float
    marginal_gain: float
    overhead_ratio: float


@dataclass(frozen=True)
class LittleEstimate:
    """Little's-law WIP target and the corresponding worker requirement."""

    target_wip: float
    required_workers: int


@dataclass(frozen=True)
class PIDTerms:
    """One discrete PID evaluation, including anti-windup state."""

    wait_signal_seconds: float
    error_seconds: float
    integral_error: float
    derivative: float
    control: float
    anti_windup: bool


@dataclass(frozen=True)
class DecisionReceipt:
    """Canonical, hash-addressed evidence for one deterministic decision."""

    schema: str
    payload: Mapping[str, object]
    digest: str

    @classmethod
    def create(cls, payload: Mapping[str, object]) -> DecisionReceipt:
        normalized = _normalise(payload)
        canonical = json.dumps(
            normalized,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return cls(
            schema="simplicio-agent/fanout-governor-receipt/v1",
            payload=MappingProxyType(normalized),
            digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    @property
    def sha256(self) -> str:
        """Compatibility alias for callers that name the digest algorithm."""

        return self.digest

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            _normalise(self.payload),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def to_dict(self) -> dict[str, object]:
        return {"schema": self.schema, "payload": dict(self.payload), "sha256": self.digest}


@dataclass(frozen=True)
class FanoutDecision:
    """Bounded decision and all model/state receipts needed to audit it."""

    desired_workers: int
    reason_codes: tuple[str, ...]
    valid_metrics: bool
    amdahl: AmdahlEstimate | None
    little: LittleEstimate | None
    pid: PIDTerms | None
    next_state: GovernorState
    receipt: DecisionReceipt

    @property
    def receipt_sha256(self) -> str:
        return self.receipt.digest

    def to_dict(self) -> dict[str, object]:
        return {
            "desired_workers": self.desired_workers,
            "reason_codes": list(self.reason_codes),
            "valid_metrics": self.valid_metrics,
            "amdahl": _dataclass_dict(self.amdahl),
            "little": _dataclass_dict(self.little),
            "pid": _dataclass_dict(self.pid),
            "next_state": _dataclass_dict(self.next_state),
            "receipt": self.receipt.to_dict(),
        }


def decide_fanout(
    metrics: FanoutMetrics,
    *,
    config: FanoutGovernorConfig | None = None,
    state: GovernorState | None = None,
) -> FanoutDecision:
    """Return one pure, bounded decision; invalid metrics fail closed.

    The function does not create workers, call the Runtime, mutate a queue, or
    persist state.  Callers choose whether and how to apply ``next_state``.
    """

    policy = config or FanoutGovernorConfig()
    prior = state or GovernorState(current_workers=metrics.current_workers if isinstance(metrics, FanoutMetrics) and _valid_integer(metrics.current_workers, minimum=1) else policy.min_workers)
    current = _bounded_current(prior.current_workers, policy)
    errors = metrics.validation_errors() if isinstance(metrics, FanoutMetrics) else ("metrics",)
    if errors:
        safe_state = GovernorState(current_workers=policy.min_workers)
        receipt = DecisionReceipt.create(
            _receipt_payload(
                metrics=metrics,
                config=policy,
                state_before=prior,
                state_after=safe_state,
                desired=policy.min_workers,
                reasons=(FanoutReasonCode.INVALID_METRICS.value,),
                valid=False,
                amdahl=None,
                little=None,
                pid=None,
                validation_errors=errors,
            )
        )
        return FanoutDecision(
            desired_workers=policy.min_workers,
            reason_codes=(FanoutReasonCode.INVALID_METRICS.value,),
            valid_metrics=False,
            amdahl=None,
            little=None,
            pid=None,
            next_state=safe_state,
            receipt=receipt,
        )

    amdahl = _amdahl(metrics, policy)
    little = _little(metrics, policy)
    pid, integral = _pid(metrics, policy, prior, current)
    reasons: list[str] = []
    if float(metrics.parallel_fraction) <= 0.0:
        reasons.append(FanoutReasonCode.SERIAL_WORK.value)

    model_target = min(
        amdahl.useful_workers,
        max(policy.min_workers, little.required_workers),
    )
    if little.required_workers > amdahl.useful_workers:
        reasons.append(FanoutReasonCode.AMDAHL_LIMIT.value)
    elif little.required_workers != current:
        reasons.append(FanoutReasonCode.LITTLE_TARGET.value)

    desired = current
    if float(metrics.parallel_fraction) <= 0.0:
        desired = max(policy.min_workers, current - policy.max_step_down)
    elif model_target > current + policy.hysteresis_workers or pid.control > policy.hysteresis_workers:
        desired = min(current + policy.max_step_up, max(model_target, current + 1), policy.max_workers)
        reasons.append(FanoutReasonCode.PID_INCREASE.value if pid.control > policy.hysteresis_workers else FanoutReasonCode.LITTLE_TARGET.value)
    elif model_target < current - policy.hysteresis_workers or pid.control < -policy.hysteresis_workers:
        desired = max(current - policy.max_step_down, min(model_target, current - 1), policy.min_workers)
        reasons.append(FanoutReasonCode.PID_DECREASE.value)
    else:
        reasons.append(FanoutReasonCode.HYSTERESIS.value)

    pressure = max(float(metrics.cpu_pressure), float(metrics.memory_pressure), float(metrics.io_pressure))
    if pressure >= policy.pressure_limit:
        desired = min(desired, max(policy.min_workers, current - policy.max_step_down))
        reasons.append(FanoutReasonCode.PRESSURE_GUARD.value)
    if float(metrics.failure_rate) >= policy.failure_rate_limit:
        desired = min(desired, max(policy.min_workers, current - policy.max_step_down))
        reasons.append(FanoutReasonCode.FAILURE_GUARD.value)

    bounded = max(policy.min_workers, min(policy.max_workers, desired))
    if bounded != desired:
        reasons.append(FanoutReasonCode.LOWER_BOUND.value if desired < policy.min_workers else FanoutReasonCode.UPPER_BOUND.value)
    if abs(bounded - current) > max(policy.max_step_up, policy.max_step_down):
        bounded = current + (policy.max_step_up if bounded > current else -policy.max_step_down)
        bounded = max(policy.min_workers, min(policy.max_workers, bounded))
        reasons.append(FanoutReasonCode.ADDITIVE_STEP.value)
    if bounded == current and not reasons:
        reasons.append(FanoutReasonCode.HOLD.value)
    reasons = _unique(reasons)

    next_state = GovernorState(
        current_workers=bounded,
        integral_error=integral,
        previous_error=pid.error_seconds,
        filtered_derivative=pid.derivative,
    )
    receipt = DecisionReceipt.create(
        _receipt_payload(
            metrics=metrics,
            config=policy,
            state_before=GovernorState(current_workers=current, integral_error=prior.integral_error, previous_error=prior.previous_error, filtered_derivative=prior.filtered_derivative),
            state_after=next_state,
            desired=bounded,
            reasons=tuple(reasons),
            valid=True,
            amdahl=amdahl,
            little=little,
            pid=pid,
            validation_errors=(),
        )
    )
    return FanoutDecision(
        desired_workers=bounded,
        reason_codes=tuple(reasons),
        valid_metrics=True,
        amdahl=amdahl,
        little=little,
        pid=pid,
        next_state=next_state,
        receipt=receipt,
    )


class AdaptiveFanoutGovernor:
    """Small stateful convenience wrapper around :func:`decide_fanout`."""

    def __init__(self, config: FanoutGovernorConfig | None = None) -> None:
        self.config = config or FanoutGovernorConfig()
        self.state = GovernorState(current_workers=self.config.min_workers)

    def decide(self, metrics: FanoutMetrics) -> FanoutDecision:
        decision = decide_fanout(metrics, config=self.config, state=self.state)
        self.state = decision.next_state
        return decision


FanoutGovernor = AdaptiveFanoutGovernor


def _amdahl(metrics: FanoutMetrics, config: FanoutGovernorConfig) -> AmdahlEstimate:
    parallel = float(metrics.parallel_fraction)
    overhead_ratio = float(metrics.overhead_per_worker_seconds) / float(metrics.service_time_seconds)
    previous = _speedup(parallel, overhead_ratio, 1)
    useful = config.min_workers
    marginal = 0.0
    for workers in range(config.min_workers + 1, config.max_workers + 1):
        speedup = _speedup(parallel, overhead_ratio, workers)
        marginal = speedup - previous
        if marginal <= overhead_ratio + 1e-12:
            break
        useful = workers
        previous = speedup
    return AmdahlEstimate(useful, _speedup(parallel, overhead_ratio, useful), marginal, overhead_ratio)


def _speedup(parallel: float, overhead_ratio: float, workers: int) -> float:
    denominator = (1.0 - parallel) + parallel / workers + overhead_ratio * max(0, workers - 1)
    return 1.0 / denominator


def _little(metrics: FanoutMetrics, config: FanoutGovernorConfig) -> LittleEstimate:
    target_wip = float(metrics.arrival_rate_per_second) * config.target_wait_seconds
    drain_rate = float(metrics.arrival_rate_per_second) + float(metrics.queue_depth) / config.target_wait_seconds
    required = max(config.min_workers, ceil(drain_rate * float(metrics.service_time_seconds)))
    return LittleEstimate(target_wip, required)


def _pid(
    metrics: FanoutMetrics,
    config: FanoutGovernorConfig,
    prior: GovernorState,
    current: int,
) -> tuple[PIDTerms, float]:
    wait_signal = max(
        float(metrics.observed_wait_seconds),
        float(metrics.queue_depth) * float(metrics.service_time_seconds) / current,
    )
    error = wait_signal - config.target_wait_seconds
    previous = prior.previous_error if prior.previous_error is not None else error
    raw_derivative = error - previous
    derivative = prior.filtered_derivative + config.derivative_filter * (raw_derivative - prior.filtered_derivative)
    integral = max(-config.integral_limit, min(config.integral_limit, prior.integral_error + error))
    control = config.pid_kp * error + config.pid_ki * integral + config.pid_kd * derivative
    anti_windup = False
    if (current >= config.max_workers and control > 0) or (current <= config.min_workers and control < 0):
        integral = prior.integral_error
        control = config.pid_kp * error + config.pid_ki * integral + config.pid_kd * derivative
        anti_windup = True
    return PIDTerms(wait_signal, error, integral, derivative, control, anti_windup), integral


def _receipt_payload(
    *,
    metrics: FanoutMetrics | object,
    config: FanoutGovernorConfig,
    state_before: GovernorState,
    state_after: GovernorState,
    desired: int,
    reasons: tuple[str, ...],
    valid: bool,
    amdahl: AmdahlEstimate | None,
    little: LittleEstimate | None,
    pid: PIDTerms | None,
    validation_errors: tuple[str, ...],
) -> dict[str, object]:
    return {
        "config": _dataclass_dict(config),
        "metrics": metrics.safe_dict() if isinstance(metrics, FanoutMetrics) else {"value": _safe_value(metrics)},
        "state_before": _dataclass_dict(state_before),
        "state_after": _dataclass_dict(state_after),
        "desired_workers": desired,
        "reason_codes": list(reasons),
        "valid_metrics": valid,
        "validation_errors": list(validation_errors),
        "amdahl": _dataclass_dict(amdahl),
        "little": _dataclass_dict(little),
        "pid": _dataclass_dict(pid),
    }


def _bounded_current(value: Any, config: FanoutGovernorConfig) -> int:
    if not _valid_integer(value, minimum=1):
        return config.min_workers
    return max(config.min_workers, min(config.max_workers, int(value)))


def _valid_number(value: Any, *, minimum: float | None = None, maximum: float | None = None, strict_positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    number = float(value)
    if not isfinite(number):
        return False
    if strict_positive and number <= 0:
        return False
    if minimum is not None and number < minimum:
        return False
    if maximum is not None and number > maximum:
        return False
    return True


def _valid_integer(value: Any, *, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _dataclass_dict(value: object) -> dict[str, object] | None:
    return None if value is None else {key: _safe_value(item) for key, item in asdict(value).items()}


def _safe_value(value: Any) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        return round(number, 12) if isfinite(number) else None
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    return None


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    return _safe_value(value)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "AdaptiveFanoutGovernor",
    "AmdahlEstimate",
    "DecisionReceipt",
    "FanoutDecision",
    "FanoutGovernor",
    "FanoutGovernorConfig",
    "FanoutMetrics",
    "FanoutReasonCode",
    "GovernorState",
    "LittleEstimate",
    "PIDTerms",
    "decide_fanout",
]
