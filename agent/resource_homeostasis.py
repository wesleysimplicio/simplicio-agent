"""Deterministic bounded-resource homeostasis controller contract.

This module is deliberately small and stdlib-only. It does not schedule work,
talk to providers, or mutate runtime state directly. It evaluates typed
resource, quality, and safety observations against hysteresis thresholds and
returns deterministic corrective actions plus receipt-safe evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


_REDACTED = "[REDACTED]"
_SECRET_MARKERS = (
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "private_key",
    "access_key",
    "refresh_key",
    "secret_key",
    "client_secret",
    "session_secret",
)


class Comparison(StrEnum):
    ABOVE = "above"
    BELOW = "below"


class HomeostasisMode(StrEnum):
    NOMINAL = "nominal"
    DEGRADED = "degraded"
    FAIL_SAFE = "fail_safe"


class ActionKind(StrEnum):
    NOOP = "noop"
    REDUCE_CONCURRENCY = "reduce_concurrency"
    SHED_LOAD = "shed_load"
    REDUCE_OPTIONAL_WORK = "reduce_optional_work"
    PAUSE_AUTONOMY = "pause_autonomy"
    ENTER_FAIL_SAFE = "enter_fail_safe"
    RESTORE_CAPACITY = "restore_capacity"


class ReceiptStatus(StrEnum):
    APPLIED = "applied"
    SKIPPED_BUDGET = "skipped_budget"


def _require_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _coerce_evidence(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("evidence must be a mapping")
    return dict(value)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def redact_evidence(value: Any) -> Any:
    """Return a receipt-safe clone with secret-like fields redacted."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            redacted[text_key] = _REDACTED if _is_secret_key(text_key) else redact_evidence(item)
        return redacted
    if isinstance(value, list):
        return [redact_evidence(item) for item in value]
    if isinstance(value, tuple):
        return [redact_evidence(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class HysteresisThreshold:
    enter: float
    exit: float
    comparison: Comparison

    def __post_init__(self) -> None:
        if isinstance(self.enter, bool) or not isinstance(self.enter, (int, float)):
            raise TypeError("enter must be numeric")
        if isinstance(self.exit, bool) or not isinstance(self.exit, (int, float)):
            raise TypeError("exit must be numeric")
        object.__setattr__(self, "enter", float(self.enter))
        object.__setattr__(self, "exit", float(self.exit))
        if not isinstance(self.comparison, Comparison):
            object.__setattr__(self, "comparison", Comparison(self.comparison))
        if self.comparison is Comparison.ABOVE and self.exit > self.enter:
            raise ValueError("ABOVE hysteresis requires exit <= enter")
        if self.comparison is Comparison.BELOW and self.exit < self.enter:
            raise ValueError("BELOW hysteresis requires exit >= enter")

    def active(self, value: float, *, was_active: bool) -> bool:
        if self.comparison is Comparison.ABOVE:
            return value >= self.exit if was_active else value >= self.enter
        return value <= self.exit if was_active else value <= self.enter


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    name: str
    value: float
    unit: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_name(self.name, "name"))
        object.__setattr__(self, "unit", _require_name(self.unit, "unit"))
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value must be numeric")
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "evidence", _coerce_evidence(self.evidence))


@dataclass(frozen=True, slots=True)
class QualityObservation:
    name: str
    value: float
    unit: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_name(self.name, "name"))
        object.__setattr__(self, "unit", _require_name(self.unit, "unit"))
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value must be numeric")
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "evidence", _coerce_evidence(self.evidence))


@dataclass(frozen=True, slots=True)
class SafetyObservation:
    name: str
    safe: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_name(self.name, "name"))
        if not isinstance(self.safe, bool):
            raise TypeError("safe must be boolean")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")
        object.__setattr__(self, "detail", self.detail.strip())
        object.__setattr__(self, "evidence", _coerce_evidence(self.evidence))


@dataclass(frozen=True, slots=True)
class CorrectiveAction:
    kind: ActionKind
    target: str | None
    reason: str
    mandatory: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActionKind):
            object.__setattr__(self, "kind", ActionKind(self.kind))
        if self.target is not None:
            object.__setattr__(self, "target", _require_name(self.target, "target"))
        object.__setattr__(self, "reason", _require_name(self.reason, "reason"))
        if not isinstance(self.mandatory, bool):
            raise TypeError("mandatory must be boolean")


@dataclass(frozen=True, slots=True)
class ActionCostReceipt:
    action: ActionKind
    target: str | None
    status: ReceiptStatus
    estimated_cost: float
    budget_before: float
    budget_after: float
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, ActionKind):
            object.__setattr__(self, "action", ActionKind(self.action))
        if self.target is not None:
            object.__setattr__(self, "target", _require_name(self.target, "target"))
        if not isinstance(self.status, ReceiptStatus):
            object.__setattr__(self, "status", ReceiptStatus(self.status))
        for field_name in ("estimated_cost", "budget_before", "budget_after"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            object.__setattr__(self, field_name, float(value))
        object.__setattr__(self, "reason", _require_name(self.reason, "reason"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "target": self.target,
            "status": self.status.value,
            "estimated_cost": self.estimated_cost,
            "budget_before": self.budget_before,
            "budget_after": self.budget_after,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class HomeostasisState:
    mode: HomeostasisMode = HomeostasisMode.NOMINAL
    active_resource_pressure: tuple[str, ...] = ()
    active_quality_pressure: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, HomeostasisMode):
            object.__setattr__(self, "mode", HomeostasisMode(self.mode))
        object.__setattr__(
            self,
            "active_resource_pressure",
            tuple(sorted({_require_name(name, "active_resource_pressure") for name in self.active_resource_pressure})),
        )
        object.__setattr__(
            self,
            "active_quality_pressure",
            tuple(sorted({_require_name(name, "active_quality_pressure") for name in self.active_quality_pressure})),
        )


@dataclass(frozen=True, slots=True)
class HomeostasisSnapshot:
    resources: tuple[ResourceObservation, ...] = ()
    quality: tuple[QualityObservation, ...] = ()
    safety: tuple[SafetyObservation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "resources", tuple(self.resources))
        object.__setattr__(self, "quality", tuple(self.quality))
        object.__setattr__(self, "safety", tuple(self.safety))


@dataclass(frozen=True, slots=True)
class HomeostasisPolicy:
    resource_thresholds: Mapping[str, HysteresisThreshold]
    quality_thresholds: Mapping[str, HysteresisThreshold]
    resource_actions: Mapping[str, ActionKind]
    quality_action: ActionKind = ActionKind.REDUCE_OPTIONAL_WORK
    fail_safe_action: ActionKind = ActionKind.ENTER_FAIL_SAFE
    pause_action: ActionKind = ActionKind.PAUSE_AUTONOMY
    restore_action: ActionKind = ActionKind.RESTORE_CAPACITY
    action_costs: Mapping[ActionKind, float] = field(default_factory=dict)
    max_total_cost: float = 0.0
    required_safety: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        resource_thresholds = {
            _require_name(name, "resource_thresholds"): threshold
            for name, threshold in self.resource_thresholds.items()
        }
        for threshold in resource_thresholds.values():
            if not isinstance(threshold, HysteresisThreshold):
                raise TypeError("resource thresholds must contain HysteresisThreshold values")
        object.__setattr__(self, "resource_thresholds", resource_thresholds)

        quality_thresholds = {
            _require_name(name, "quality_thresholds"): threshold
            for name, threshold in self.quality_thresholds.items()
        }
        for threshold in quality_thresholds.values():
            if not isinstance(threshold, HysteresisThreshold):
                raise TypeError("quality thresholds must contain HysteresisThreshold values")
        object.__setattr__(self, "quality_thresholds", quality_thresholds)

        resource_actions = {
            _require_name(name, "resource_actions"): ActionKind(action)
            for name, action in self.resource_actions.items()
        }
        object.__setattr__(self, "resource_actions", resource_actions)

        if not isinstance(self.quality_action, ActionKind):
            object.__setattr__(self, "quality_action", ActionKind(self.quality_action))
        if not isinstance(self.fail_safe_action, ActionKind):
            object.__setattr__(self, "fail_safe_action", ActionKind(self.fail_safe_action))
        if not isinstance(self.pause_action, ActionKind):
            object.__setattr__(self, "pause_action", ActionKind(self.pause_action))
        if not isinstance(self.restore_action, ActionKind):
            object.__setattr__(self, "restore_action", ActionKind(self.restore_action))

        costs: dict[ActionKind, float] = {}
        for action, value in self.action_costs.items():
            kind = action if isinstance(action, ActionKind) else ActionKind(action)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError("action costs must be non-negative numbers")
            costs[kind] = float(value)
        object.__setattr__(self, "action_costs", costs)

        if (
            isinstance(self.max_total_cost, bool)
            or not isinstance(self.max_total_cost, (int, float))
            or self.max_total_cost < 0
        ):
            raise ValueError("max_total_cost must be a non-negative number")
        object.__setattr__(self, "max_total_cost", float(self.max_total_cost))
        object.__setattr__(
            self,
            "required_safety",
            tuple(sorted({_require_name(name, "required_safety") for name in self.required_safety})),
        )

    def action_cost(self, action: ActionKind) -> float:
        return self.action_costs.get(action, 0.0)


@dataclass(frozen=True, slots=True)
class HomeostasisDecision:
    mode: HomeostasisMode
    state: HomeostasisState
    actions: tuple[CorrectiveAction, ...]
    receipts: tuple[ActionCostReceipt, ...]
    reasons: tuple[str, ...]
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, HomeostasisMode):
            object.__setattr__(self, "mode", HomeostasisMode(self.mode))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "state": {
                "mode": self.state.mode.value,
                "active_resource_pressure": list(self.state.active_resource_pressure),
                "active_quality_pressure": list(self.state.active_quality_pressure),
            },
            "actions": [
                {
                    "kind": action.kind.value,
                    "target": action.target,
                    "reason": action.reason,
                    "mandatory": action.mandatory,
                }
                for action in self.actions
            ],
            "receipts": [receipt.to_dict() for receipt in self.receipts],
            "reasons": list(self.reasons),
            "evidence": self.evidence,
        }


class ResourceHomeostasisController:
    """Pure evaluator for bounded-resource homeostasis decisions."""

    def __init__(self, policy: HomeostasisPolicy) -> None:
        if not isinstance(policy, HomeostasisPolicy):
            raise TypeError("policy must be a HomeostasisPolicy")
        self.policy = policy

    def evaluate(
        self,
        snapshot: HomeostasisSnapshot,
        *,
        state: HomeostasisState | None = None,
    ) -> HomeostasisDecision:
        if not isinstance(snapshot, HomeostasisSnapshot):
            raise TypeError("snapshot must be a HomeostasisSnapshot")
        state = state or HomeostasisState()

        resource_map = {item.name: item for item in snapshot.resources}
        quality_map = {item.name: item for item in snapshot.quality}
        safety_map = {item.name: item for item in snapshot.safety}

        missing_reasons = []
        missing_safety = [
            name for name in self.policy.required_safety if name not in safety_map
        ]
        if missing_safety:
            missing_reasons.extend(f"missing_safety:{name}" for name in missing_safety)

        active_resource_pressure = []
        for name in sorted(self.policy.resource_thresholds):
            observation = resource_map.get(name)
            if observation is None:
                missing_reasons.append(f"missing_resource:{name}")
                continue
            threshold = self.policy.resource_thresholds[name]
            was_active = name in state.active_resource_pressure
            if threshold.active(observation.value, was_active=was_active):
                active_resource_pressure.append(name)

        active_quality_pressure = []
        for name in sorted(self.policy.quality_thresholds):
            observation = quality_map.get(name)
            if observation is None:
                missing_reasons.append(f"missing_quality:{name}")
                continue
            threshold = self.policy.quality_thresholds[name]
            was_active = name in state.active_quality_pressure
            if threshold.active(observation.value, was_active=was_active):
                active_quality_pressure.append(name)

        unsafe_checks = sorted(name for name, item in safety_map.items() if not item.safe)

        reasons = sorted(
            set(
                [f"unsafe:{name}" for name in unsafe_checks]
                + missing_reasons
                + [f"resource_pressure:{name}" for name in active_resource_pressure]
                + [f"quality_pressure:{name}" for name in active_quality_pressure]
            )
        )

        if unsafe_checks or missing_reasons:
            mode = HomeostasisMode.FAIL_SAFE
        elif active_resource_pressure or active_quality_pressure:
            mode = HomeostasisMode.DEGRADED
        else:
            mode = HomeostasisMode.NOMINAL

        actions = self._candidate_actions(mode, state, active_resource_pressure, active_quality_pressure, reasons)
        applied_actions, receipts = self._materialize_actions(actions)

        next_state = HomeostasisState(
            mode=mode,
            active_resource_pressure=tuple(active_resource_pressure),
            active_quality_pressure=tuple(active_quality_pressure),
        )

        evidence = redact_evidence(
            {
                "resources": {
                    name: {
                        "value": resource_map[name].value,
                        "unit": resource_map[name].unit,
                        "evidence": resource_map[name].evidence,
                    }
                    for name in sorted(resource_map)
                },
                "quality": {
                    name: {
                        "value": quality_map[name].value,
                        "unit": quality_map[name].unit,
                        "evidence": quality_map[name].evidence,
                    }
                    for name in sorted(quality_map)
                },
                "safety": {
                    name: {
                        "safe": safety_map[name].safe,
                        "detail": safety_map[name].detail,
                        "evidence": safety_map[name].evidence,
                    }
                    for name in sorted(safety_map)
                },
            }
        )

        return HomeostasisDecision(
            mode=mode,
            state=next_state,
            actions=tuple(applied_actions),
            receipts=tuple(receipts),
            reasons=tuple(reasons),
            evidence=evidence,
        )

    def _candidate_actions(
        self,
        mode: HomeostasisMode,
        state: HomeostasisState,
        active_resource_pressure: list[str],
        active_quality_pressure: list[str],
        reasons: list[str],
    ) -> list[CorrectiveAction]:
        actions: list[CorrectiveAction] = []
        if mode is HomeostasisMode.FAIL_SAFE:
            actions.append(
                CorrectiveAction(
                    self.policy.fail_safe_action,
                    None,
                    "fail_safe_required",
                    mandatory=True,
                )
            )
            actions.append(
                CorrectiveAction(
                    self.policy.pause_action,
                    None,
                    "pause_autonomy_until_safe",
                    mandatory=True,
                )
            )
        for name in sorted(active_resource_pressure):
            actions.append(
                CorrectiveAction(
                    self.policy.resource_actions.get(name, ActionKind.SHED_LOAD),
                    name,
                    f"resource_pressure:{name}",
                    mandatory=mode is HomeostasisMode.FAIL_SAFE,
                )
            )
        for name in sorted(active_quality_pressure):
            actions.append(
                CorrectiveAction(
                    self.policy.quality_action,
                    name,
                    f"quality_pressure:{name}",
                    mandatory=mode is HomeostasisMode.FAIL_SAFE,
                )
            )
        if (
            mode is HomeostasisMode.NOMINAL
            and state.mode is not HomeostasisMode.NOMINAL
            and (state.active_resource_pressure or state.active_quality_pressure or reasons == [])
        ):
            actions.append(
                CorrectiveAction(
                    self.policy.restore_action,
                    None,
                    "restore_capacity_after_recovery",
                )
            )
        if not actions:
            actions.append(CorrectiveAction(ActionKind.NOOP, None, "no_pressure_detected"))
        return actions

    def _materialize_actions(
        self,
        actions: list[CorrectiveAction],
    ) -> tuple[list[CorrectiveAction], list[ActionCostReceipt]]:
        remaining_budget = self.policy.max_total_cost
        applied: list[CorrectiveAction] = []
        receipts: list[ActionCostReceipt] = []
        for action in actions:
            cost = self.policy.action_cost(action.kind)
            budget_before = remaining_budget
            fits_budget = action.mandatory or cost <= remaining_budget
            if fits_budget:
                remaining_budget = max(0.0, remaining_budget - cost)
                applied.append(action)
                status = ReceiptStatus.APPLIED
            else:
                status = ReceiptStatus.SKIPPED_BUDGET
            receipts.append(
                ActionCostReceipt(
                    action=action.kind,
                    target=action.target,
                    status=status,
                    estimated_cost=cost,
                    budget_before=budget_before,
                    budget_after=remaining_budget if status is ReceiptStatus.APPLIED else budget_before,
                    reason=action.reason,
                )
            )
        return applied, receipts


__all__ = [
    "ActionCostReceipt",
    "ActionKind",
    "Comparison",
    "CorrectiveAction",
    "HomeostasisDecision",
    "HomeostasisMode",
    "HomeostasisPolicy",
    "HomeostasisSnapshot",
    "HomeostasisState",
    "HysteresisThreshold",
    "QualityObservation",
    "ReceiptStatus",
    "ResourceHomeostasisController",
    "ResourceObservation",
    "SafetyObservation",
    "redact_evidence",
]
