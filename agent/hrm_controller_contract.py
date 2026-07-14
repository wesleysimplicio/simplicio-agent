"""Bounded additive two-scale controller contract for issue #138.

This is a pure data/control contract.  It separates a bounded high-level plan
from low-level AC-scoped steps, but it does not integrate cognition, models,
delegation, or the simplicio-loop scratchpad.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = "hrm-controller/v1"
MAX_TEXT_LENGTH = 512
MAX_MACHINE_SUMMARY_LENGTH = 768
MAX_EVIDENCE_ITEMS = 16
MAX_RECEIPTS = 256
_TOKEN_RE = re.compile(r"^[^\x00-\x1f\x7f\s]+$")


class Phase(StrEnum):
    """Phases shared with the simplicio-loop hierarchical planner."""

    EXPLORE = "explore"
    DEBUG = "debug"
    HARDEN = "harden"
    REFACTOR = "refactor"
    IMPLEMENT = "implement"
    ESCALATE = "escalate"


SUPPORTED_PHASES: tuple[Phase, ...] = tuple(Phase)


class ReplanReason(StrEnum):
    """Events that are permitted to invoke the high-level planner."""

    START = "start"
    PHASE_BOUNDARY = "phase_boundary"
    ANCHOR_DRIFT = "anchor_drift"
    STALL = "stall"


class EvidenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


ReceiptStatus = EvidenceStatus


class HRMControllerError(ValueError):
    """Base error for invalid or unsafe controller transitions."""


class InvalidControllerValue(HRMControllerError):
    """Raised when a contract value cannot be accepted safely."""


class LowLevelMutationError(HRMControllerError):
    """Raised when a low-level step attempts to change slow state."""


class PlannerBudgetExceeded(HRMControllerError):
    """Raised before a high-level call would exceed its hard budget."""


class MaxIterationsExceeded(HRMControllerError):
    """Raised before a low-level step would exceed its hard iteration bound."""


class StallEscalationError(HRMControllerError):
    """Raised when a true stall does not produce a different strategy."""


class PlannerContractError(HRMControllerError):
    """Raised when the high-level planner returns an invalid plan."""


def _text(value: object, name: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length or not _TOKEN_RE.match(value):
        raise InvalidControllerValue(f"{name} must be a bounded non-empty token")
    return value


def _description(value: object, name: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise InvalidControllerValue(f"{name} must be a bounded non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InvalidControllerValue(f"{name} contains control characters")
    return value


def _positive_int(value: object, name: str, *, maximum: int = 100_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise InvalidControllerValue(f"{name} must be a positive bounded integer")
    return value


def _phase(value: object, name: str = "phase") -> Phase:
    try:
        return value if isinstance(value, Phase) else Phase(value)
    except (TypeError, ValueError) as exc:
        raise InvalidControllerValue(f"{name} must be one of the supported phases") from exc


def _reason(value: object) -> ReplanReason:
    try:
        return value if isinstance(value, ReplanReason) else ReplanReason(value)
    except (TypeError, ValueError) as exc:
        raise InvalidControllerValue("reason is not a permitted replan reason") from exc


def _evidence(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvalidControllerValue("evidence must be a bounded sequence of strings")
    if len(value) > MAX_EVIDENCE_ITEMS:
        raise InvalidControllerValue("evidence exceeds the bounded item count")
    return tuple(_description(item, "evidence item") for item in value)


def _canonical(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FastState:
    """Low-level execution state; it cannot select a phase or AC."""

    iteration: int = 0
    max_iterations: int = 1
    last_fingerprint: str | None = None
    consecutive_fingerprint_count: int = 0
    halted: bool = False

    def __post_init__(self) -> None:
        _positive_int(self.max_iterations, "max_iterations")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or not 0 <= self.iteration <= self.max_iterations:
            raise InvalidControllerValue("iteration must be within max_iterations")
        if self.last_fingerprint is not None:
            _text(self.last_fingerprint, "last_fingerprint")
        if isinstance(self.consecutive_fingerprint_count, bool) or not isinstance(self.consecutive_fingerprint_count, int):
            raise InvalidControllerValue("consecutive_fingerprint_count must be an integer")
        if not 0 <= self.consecutive_fingerprint_count <= self.iteration:
            raise InvalidControllerValue("consecutive_fingerprint_count is invalid")
        if not isinstance(self.halted, bool):
            raise InvalidControllerValue("halted must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "last_fingerprint": self.last_fingerprint,
            "consecutive_fingerprint_count": self.consecutive_fingerprint_count,
            "halted": self.halted,
        }


@dataclass(frozen=True)
class SlowState:
    """High-level state passed to the planner, without transcript content."""

    anchor_hash: str
    acceptance_criteria_hash: str
    phase: Phase
    hypothesis: str
    strategy: str
    plan_hash: str | None = None
    planner_calls: int = 0
    planner_call_budget: int = 1
    last_replan_reason: ReplanReason | None = None

    def __post_init__(self) -> None:
        _text(self.anchor_hash, "anchor_hash", max_length=128)
        _text(self.acceptance_criteria_hash, "acceptance_criteria_hash", max_length=128)
        _phase(self.phase)
        _description(self.hypothesis, "hypothesis")
        _text(self.strategy, "strategy")
        if self.plan_hash is not None:
            _text(self.plan_hash, "plan_hash", max_length=128)
        if isinstance(self.planner_calls, bool) or not isinstance(self.planner_calls, int) or self.planner_calls < 0:
            raise InvalidControllerValue("planner_calls must be a non-negative integer")
        _positive_int(self.planner_call_budget, "planner_call_budget")
        if self.planner_calls > self.planner_call_budget:
            raise InvalidControllerValue("planner_calls exceed planner_call_budget")
        if self.last_replan_reason is not None:
            _reason(self.last_replan_reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_hash": self.anchor_hash,
            "acceptance_criteria_hash": self.acceptance_criteria_hash,
            "phase": self.phase.value,
            "hypothesis": self.hypothesis,
            "strategy": self.strategy,
            "plan_hash": self.plan_hash,
            "planner_calls": self.planner_calls,
            "planner_call_budget": self.planner_call_budget,
            "last_replan_reason": self.last_replan_reason.value if self.last_replan_reason else None,
        }


@dataclass(frozen=True)
class Plan:
    """Bounded high-level plan returned by a deterministic planner callback."""

    phase: Phase
    hypothesis: str
    strategy: str
    anchor_hash: str
    acceptance_criteria_hash: str
    machine_summary: str
    evidence: tuple[str, ...] = ()
    inferred: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", _phase(self.phase))
        _description(self.hypothesis, "plan.hypothesis")
        _text(self.strategy, "plan.strategy")
        _text(self.anchor_hash, "plan.anchor_hash", max_length=128)
        _text(self.acceptance_criteria_hash, "plan.acceptance_criteria_hash", max_length=128)
        _description(self.machine_summary, "plan.machine_summary", max_length=MAX_MACHINE_SUMMARY_LENGTH)
        object.__setattr__(self, "evidence", _evidence(self.evidence))
        if not isinstance(self.inferred, bool):
            raise InvalidControllerValue("plan.inferred must be boolean")

    @property
    def plan_hash(self) -> str:
        return _digest(self.to_dict(include_hash=False))

    @property
    def evidence_status(self) -> EvidenceStatus:
        return EvidenceStatus.UNVERIFIED if self.inferred or not self.evidence else EvidenceStatus.VERIFIED

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "phase": self.phase.value,
            "hypothesis": self.hypothesis,
            "strategy": self.strategy,
            "anchor_hash": self.anchor_hash,
            "acceptance_criteria_hash": self.acceptance_criteria_hash,
            "machine_summary": self.machine_summary,
            "evidence": list(self.evidence),
            "inferred": self.inferred,
        }
        if include_hash:
            payload["plan_hash"] = self.plan_hash
        return payload


@dataclass(frozen=True)
class TransitionReceipt:
    """Deterministic, evidence-labelled record for each high-level transition."""

    sequence: int
    from_phase: Phase | None
    to_phase: Phase
    reason: ReplanReason
    anchor_hash: str
    iteration: int
    evidence: tuple[str, ...] = ()
    inferred: bool = False

    def __post_init__(self) -> None:
        _positive_int(self.sequence, "receipt.sequence", maximum=MAX_RECEIPTS)
        if self.from_phase is not None:
            object.__setattr__(self, "from_phase", _phase(self.from_phase, "receipt.from_phase"))
        object.__setattr__(self, "to_phase", _phase(self.to_phase, "receipt.to_phase"))
        object.__setattr__(self, "reason", _reason(self.reason))
        _text(self.anchor_hash, "receipt.anchor_hash", max_length=128)
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise InvalidControllerValue("receipt.iteration must be non-negative")
        object.__setattr__(self, "evidence", _evidence(self.evidence))
        if not isinstance(self.inferred, bool):
            raise InvalidControllerValue("receipt.inferred must be boolean")

    @property
    def status(self) -> EvidenceStatus:
        return EvidenceStatus.UNVERIFIED if self.inferred or not self.evidence else EvidenceStatus.VERIFIED

    @property
    def evidence_status(self) -> EvidenceStatus:
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "from_phase": self.from_phase.value if self.from_phase else None,
            "to_phase": self.to_phase.value,
            "reason": self.reason.value,
            "anchor_hash": self.anchor_hash,
            "iteration": self.iteration,
            "evidence": list(self.evidence),
            "status": self.status.value,
            "inferred": self.inferred,
        }


@dataclass(frozen=True)
class StepReceipt:
    """Bounded receipt for one low-level AC-scoped step."""

    iteration: int
    action_fingerprint: str
    phase: Phase
    consecutive_fingerprint_count: int
    transition: TransitionReceipt | None = None

    def __post_init__(self) -> None:
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration <= 0:
            raise InvalidControllerValue("step.iteration must be positive")
        _text(self.action_fingerprint, "action_fingerprint")
        object.__setattr__(self, "phase", _phase(self.phase, "step.phase"))
        if isinstance(self.consecutive_fingerprint_count, bool) or not isinstance(self.consecutive_fingerprint_count, int) or self.consecutive_fingerprint_count <= 0:
            raise InvalidControllerValue("step consecutive count must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "action_fingerprint": self.action_fingerprint,
            "phase": self.phase.value,
            "consecutive_fingerprint_count": self.consecutive_fingerprint_count,
            "transition": self.transition.to_dict() if self.transition else None,
        }


@dataclass(frozen=True)
class ControllerState:
    """Versioned view combining the fast and slow state scales."""

    schema: str
    anchor_hash: str
    acceptance_criteria_hash: str
    phase: Phase
    hypothesis: str
    budget: int
    iteration: int
    last_replan_reason: ReplanReason | None
    fast: FastState
    slow: SlowState

    def __post_init__(self) -> None:
        if self.schema != SCHEMA_VERSION:
            raise InvalidControllerValue("unsupported controller schema")
        _text(self.anchor_hash, "state.anchor_hash", max_length=128)
        _text(self.acceptance_criteria_hash, "state.acceptance_criteria_hash", max_length=128)
        _phase(self.phase)
        _description(self.hypothesis, "state.hypothesis")
        _positive_int(self.budget, "state.budget")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise InvalidControllerValue("state.iteration must be non-negative")
        if self.last_replan_reason is not None:
            _reason(self.last_replan_reason)

    @property
    def planner_calls_remaining(self) -> int:
        return self.slow.planner_call_budget - self.slow.planner_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "anchor_hash": self.anchor_hash,
            "acceptance_criteria_hash": self.acceptance_criteria_hash,
            "phase": self.phase.value,
            "hypothesis": self.hypothesis,
            "budget": self.budget,
            "iteration": self.iteration,
            "last_replan_reason": self.last_replan_reason.value if self.last_replan_reason else None,
            "fast": self.fast.to_dict(),
            "slow": self.slow.to_dict(),
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict())


Planner = Callable[[SlowState], Plan | Mapping[str, Any]]


class HRMController:
    """A bounded high-level planner plus an AC-scoped low-level executor."""

    def __init__(
        self,
        *,
        anchor_hash: str,
        acceptance_criteria_hash: str,
        hypothesis: str,
        phase: Phase = Phase.EXPLORE,
        max_iterations: int = 32,
        planner_call_budget: int = 8,
        stall_threshold: int = 3,
        planner: Planner | None = None,
    ) -> None:
        _text(anchor_hash, "anchor_hash", max_length=128)
        _text(acceptance_criteria_hash, "acceptance_criteria_hash", max_length=128)
        _description(hypothesis, "hypothesis")
        phase = _phase(phase)
        _positive_int(max_iterations, "max_iterations")
        _positive_int(planner_call_budget, "planner_call_budget")
        _positive_int(stall_threshold, "stall_threshold", maximum=MAX_TEXT_LENGTH)
        if planner is not None and not callable(planner):
            raise InvalidControllerValue("planner must be callable")
        self._planner = planner or self._default_planner
        self._stall_threshold = stall_threshold
        self._started = False
        self._plan: Plan | None = None
        self._receipts: tuple[TransitionReceipt, ...] = ()
        fast = FastState(max_iterations=max_iterations)
        slow = SlowState(
            anchor_hash=anchor_hash,
            acceptance_criteria_hash=acceptance_criteria_hash,
            phase=phase,
            hypothesis=hypothesis,
            strategy="unplanned",
            planner_call_budget=planner_call_budget,
        )
        self._state = ControllerState(
            schema=SCHEMA_VERSION,
            anchor_hash=anchor_hash,
            acceptance_criteria_hash=acceptance_criteria_hash,
            phase=phase,
            hypothesis=hypothesis,
            budget=planner_call_budget,
            iteration=0,
            last_replan_reason=None,
            fast=fast,
            slow=slow,
        )

    @staticmethod
    def _default_planner(slow: SlowState) -> Plan:
        strategy = f"{slow.phase.value}-strategy-{slow.planner_calls + 1}"
        return Plan(
            phase=slow.phase,
            hypothesis=slow.hypothesis,
            strategy=strategy,
            anchor_hash=slow.anchor_hash,
            acceptance_criteria_hash=slow.acceptance_criteria_hash,
            machine_summary=(
                f"phase={slow.phase.value};ac={slow.acceptance_criteria_hash};"
                f"anchor={slow.anchor_hash};strategy={strategy}"
            ),
            evidence=("deterministic contract planner",),
        )

    @property
    def state(self) -> ControllerState:
        return self._state

    @property
    def plan(self) -> Plan | None:
        return self._plan

    @property
    def receipts(self) -> tuple[TransitionReceipt, ...]:
        return self._receipts

    @property
    def planner_calls(self) -> int:
        return self._state.slow.planner_calls

    @property
    def planner_calls_remaining(self) -> int:
        return self._state.planner_calls_remaining

    def start(self, *, evidence: Sequence[str] | None = ("controller start",)) -> ControllerState:
        """Plan once; subsequent calls reuse the plan without a planner call."""

        if self._started:
            return self._state
        self._replan(ReplanReason.START, evidence=evidence)
        return self._state

    def phase_boundary(self, phase: Phase, *, evidence: Sequence[str] | None = None) -> TransitionReceipt:
        """Move phase only through an explicit high-level boundary."""

        if not self._started:
            raise HRMControllerError("controller must be started before a phase boundary")
        requested = _phase(phase, "phase_boundary.phase")
        if evidence is None:
            raise InvalidControllerValue("phase boundary requires evidence")
        return self._replan(ReplanReason.PHASE_BOUNDARY, requested_phase=requested, evidence=evidence)

    def execute_step(
        self,
        action_fingerprint: str,
        *,
        phase: Phase | None = None,
        acceptance_criteria_hash: str | None = None,
        anchor_hash: str | None = None,
        evidence: Sequence[str] | None = None,
    ) -> StepReceipt:
        """Execute one bounded step without allowing low-level slow-state mutation."""

        if not self._started or self._plan is None:
            raise HRMControllerError("controller must be started before execution")
        fingerprint = _text(action_fingerprint, "action_fingerprint")
        if phase is not None and _phase(phase, "low-level phase") != self._state.phase:
            raise LowLevelMutationError("low-level execution cannot change phase")
        if acceptance_criteria_hash is not None and acceptance_criteria_hash != self._state.acceptance_criteria_hash:
            raise LowLevelMutationError("low-level execution cannot change acceptance criteria")
        if self._state.fast.halted or self._state.iteration >= self._state.fast.max_iterations:
            self._state = replace(self._state, fast=replace(self._state.fast, halted=True))
            raise MaxIterationsExceeded("max_iterations reached")
        transition: TransitionReceipt | None = None
        if anchor_hash is not None:
            _text(anchor_hash, "anchor_hash", max_length=128)
            if anchor_hash != self._state.anchor_hash:
                transition = self._replan(
                    ReplanReason.ANCHOR_DRIFT,
                    new_anchor_hash=anchor_hash,
                    evidence=evidence,
                )
        previous = self._state.fast
        count = previous.consecutive_fingerprint_count + 1 if previous.last_fingerprint == fingerprint else 1
        fast = replace(
            previous,
            iteration=previous.iteration + 1,
            last_fingerprint=fingerprint,
            consecutive_fingerprint_count=count,
            halted=previous.iteration + 1 >= previous.max_iterations,
        )
        self._state = replace(self._state, iteration=fast.iteration, fast=fast)
        if count >= self._stall_threshold:
            stall_transition = self._replan(ReplanReason.STALL, evidence=evidence)
            transition = stall_transition if transition is None else transition
            fast = replace(self._state.fast, last_fingerprint=None, consecutive_fingerprint_count=0)
            self._state = replace(self._state, fast=fast)
        return StepReceipt(
            iteration=self._state.iteration,
            action_fingerprint=fingerprint,
            phase=self._state.phase,
            consecutive_fingerprint_count=count,
            transition=transition,
        )

    def machine_summary(self) -> dict[str, Any]:
        """Return only bounded state suitable for delegation or kanban handoff."""

        return {
            "schema": SCHEMA_VERSION,
            "anchor_hash": self._state.anchor_hash,
            "acceptance_criteria_hash": self._state.acceptance_criteria_hash,
            "phase": self._state.phase.value,
            "hypothesis": self._state.hypothesis,
            "strategy": self._plan.strategy if self._plan else None,
            "iteration": self._state.iteration,
            "budget": self._state.budget,
            "planner_calls": self._state.slow.planner_calls,
            "last_replan_reason": self._state.last_replan_reason.value if self._state.last_replan_reason else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "state": self._state.to_dict(),
            "plan": self._plan.to_dict() if self._plan else None,
            "receipts": [receipt.to_dict() for receipt in self._receipts],
            "stall_threshold": self._stall_threshold,
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict())

    def _replan(
        self,
        reason: ReplanReason,
        *,
        requested_phase: Phase | None = None,
        new_anchor_hash: str | None = None,
        evidence: Sequence[str] | None,
    ) -> TransitionReceipt:
        reason = _reason(reason)
        if self._state.slow.planner_calls >= self._state.slow.planner_call_budget:
            raise PlannerBudgetExceeded("planner_call_budget reached")
        if reason is ReplanReason.PHASE_BOUNDARY and requested_phase is None:
            raise InvalidControllerValue("phase boundary requires a requested phase")
        anchor = new_anchor_hash or self._state.anchor_hash
        _text(anchor, "anchor_hash", max_length=128)
        current = self._state
        planner_input = replace(
            current.slow,
            anchor_hash=anchor,
            phase=requested_phase or current.phase,
            planner_calls=current.slow.planner_calls,
            last_replan_reason=reason,
        )
        try:
            candidate = self._planner(planner_input)
            plan = candidate if isinstance(candidate, Plan) else Plan(**dict(candidate)) if isinstance(candidate, Mapping) else None
        except HRMControllerError:
            raise
        except Exception as exc:
            raise PlannerContractError("planner returned an invalid plan") from exc
        if plan is None:
            raise PlannerContractError("planner must return Plan or mapping")
        if plan.anchor_hash != anchor:
            raise PlannerContractError("planner changed anchor_hash without matching drift")
        if plan.acceptance_criteria_hash != current.acceptance_criteria_hash:
            raise PlannerContractError("planner changed acceptance_criteria_hash")
        if reason is ReplanReason.PHASE_BOUNDARY and plan.phase != requested_phase:
            raise PlannerContractError("phase-boundary planner must honor requested phase")
        if reason is ReplanReason.ANCHOR_DRIFT and plan.phase != current.phase:
            raise PlannerContractError("anchor drift cannot change phase without a boundary")
        if reason is ReplanReason.STALL and plan.phase not in (current.phase, Phase.ESCALATE):
            raise PlannerContractError("stall may preserve phase or escalate")
        if reason is ReplanReason.STALL and self._plan is not None and plan.strategy == self._plan.strategy and plan.phase != Phase.ESCALATE:
            raise StallEscalationError("stall replan must change strategy or escalate")
        items = _evidence(evidence)
        receipt = TransitionReceipt(
            sequence=len(self._receipts) + 1,
            from_phase=current.phase,
            to_phase=plan.phase,
            reason=reason,
            anchor_hash=anchor,
            iteration=current.iteration,
            evidence=items,
            inferred=plan.inferred,
        )
        calls = current.slow.planner_calls + 1
        slow = SlowState(
            anchor_hash=anchor,
            acceptance_criteria_hash=current.acceptance_criteria_hash,
            phase=plan.phase,
            hypothesis=plan.hypothesis,
            strategy=plan.strategy,
            plan_hash=plan.plan_hash,
            planner_calls=calls,
            planner_call_budget=current.slow.planner_call_budget,
            last_replan_reason=reason,
        )
        self._plan = plan
        self._receipts = self._receipts + (receipt,)
        self._state = ControllerState(
            schema=SCHEMA_VERSION,
            anchor_hash=anchor,
            acceptance_criteria_hash=current.acceptance_criteria_hash,
            phase=plan.phase,
            hypothesis=plan.hypothesis,
            budget=current.budget,
            iteration=current.iteration,
            last_replan_reason=reason,
            fast=current.fast,
            slow=slow,
        )
        self._started = True
        return receipt


__all__ = [
    "ControllerState",
    "EvidenceStatus",
    "FastState",
    "HRMController",
    "HRMControllerError",
    "InvalidControllerValue",
    "LowLevelMutationError",
    "MAX_EVIDENCE_ITEMS",
    "MAX_MACHINE_SUMMARY_LENGTH",
    "MAX_RECEIPTS",
    "MAX_TEXT_LENGTH",
    "MaxIterationsExceeded",
    "Phase",
    "Plan",
    "PlannerBudgetExceeded",
    "PlannerContractError",
    "ReceiptStatus",
    "ReplanReason",
    "SUPPORTED_PHASES",
    "SlowState",
    "StallEscalationError",
    "StepReceipt",
    "TransitionReceipt",
    "SCHEMA_VERSION",
]
