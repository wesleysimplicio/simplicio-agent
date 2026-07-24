"""Deterministic semantic no-progress guard for Agent tool calls.

The guard only decides whether a proposed call may proceed and records bounded
progress evidence. It never executes tools, calls a model, or owns scheduling.
The Simplicio Loop can consume :class:`GuardDecision` without parsing prose.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = "simplicio.agent.no-progress/v1"
_SECRET_KEY_PARTS = ("authorization", "cookie", "password", "secret", "token", "api_key", "private_key")


class GuardAction(str, Enum):
    ALLOW = "allow"
    NOTICE = "notice"
    VETO = "veto"
    REPLAN = "replan"
    TERMINATE = "terminate"


class GuardReason(str, Enum):
    FIRST_OBSERVATION = "first_observation"
    PROGRESS_OBSERVED = "progress_observed"
    POLLING_EXCEPTION = "declared_polling_exception"
    REPEATED_NO_PROGRESS = "repeated_no_progress"
    EXACT_CALL_VETO = "exact_call_veto"
    REPLAN_REQUIRED = "replan_required"
    HARD_TERMINATION = "hard_termination"


@dataclass(frozen=True, slots=True)
class GuardPolicy:
    """Bounded recovery thresholds for one Agent session."""

    warning_threshold: int = 3
    veto_threshold: int = 5
    hard_threshold: int = 8
    replan_threshold: int = 2
    journal_limit: int = 64

    def __post_init__(self) -> None:
        values = (
            self.warning_threshold,
            self.veto_threshold,
            self.hard_threshold,
            self.replan_threshold,
            self.journal_limit,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("guard thresholds and journal_limit must be positive integers")
        if not self.warning_threshold < self.veto_threshold < self.hard_threshold:
            raise ValueError("thresholds must satisfy warning < veto < hard")


@dataclass(frozen=True, slots=True)
class GuardDecision:
    """A typed, redacted decision that Loop can consume directly."""

    action: GuardAction
    reason: GuardReason
    call_fingerprint: str
    repeated_count: int
    evidence_delta: int = 0
    notice: str = ""
    terminal_status: str | None = None
    receipt: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.action, GuardAction):
            object.__setattr__(self, "action", GuardAction(self.action))
        if not isinstance(self.reason, GuardReason):
            object.__setattr__(self, "reason", GuardReason(self.reason))
        if len(self.call_fingerprint) != 64:
            raise ValueError("call_fingerprint must be a SHA-256 hex digest")
        if not isinstance(self.repeated_count, int) or self.repeated_count < 0:
            raise ValueError("repeated_count must be a non-negative integer")
        if not isinstance(self.evidence_delta, int) or self.evidence_delta < 0:
            raise ValueError("evidence_delta must be a non-negative integer")
        if self.action is GuardAction.TERMINATE and self.terminal_status != "blocked_no_progress":
            raise ValueError("terminate decisions must be blocked_no_progress")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "action": self.action.value,
            "reason": self.reason.value,
            "call_fingerprint": self.call_fingerprint,
            "repeated_count": self.repeated_count,
            "evidence_delta": self.evidence_delta,
            "notice": self.notice,
            "terminal_status": self.terminal_status,
            "receipt": dict(self.receipt),
        }


@dataclass
class _JournalEntry:
    tool_name: str
    call_fingerprint: str
    last_result_fingerprint: str = ""
    last_world_state_fingerprint: str = ""
    last_failure_code: str = ""
    evidence_count: int = 0
    no_progress_count: int = 0
    replan_count: int = 0


def _canonical(value: Any, *, key: str = "") -> Any:
    """Build a deterministic, secret-free shape for hashing only."""

    lowered = key.lower()
    if any(part in lowered for part in _SECRET_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k], key=str(k)) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        return sorted((_canonical(item) for item in value), key=repr)
    if isinstance(value, float):
        return format(value, ".17g")
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt(event: str, sequence: int, fingerprint: str, count: int, evidence_delta: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "sequence": sequence,
        "call_fingerprint": fingerprint,
        "repeated_count": count,
        "evidence_delta": evidence_delta,
    }


class NoProgressGuard:
    """Per-session bounded guard; safe to call before and after dispatch."""

    def __init__(self, policy: GuardPolicy | None = None) -> None:
        self.policy = policy or GuardPolicy()
        self._entries: OrderedDict[str, _JournalEntry] = OrderedDict()
        self._sequence = 0

    def _touch(self, entry: _JournalEntry) -> None:
        self._entries.pop(entry.call_fingerprint, None)
        self._entries[entry.call_fingerprint] = entry
        while len(self._entries) > self.policy.journal_limit:
            self._entries.popitem(last=False)

    def _decision(
        self,
        *,
        action: GuardAction,
        reason: GuardReason,
        entry: _JournalEntry,
        evidence_delta: int = 0,
        notice: str = "",
        terminal_status: str | None = None,
    ) -> GuardDecision:
        self._sequence += 1
        return GuardDecision(
            action=action,
            reason=reason,
            call_fingerprint=entry.call_fingerprint,
            repeated_count=entry.no_progress_count,
            evidence_delta=evidence_delta,
            notice=notice,
            terminal_status=terminal_status,
            receipt=_receipt(
                reason.value,
                self._sequence,
                entry.call_fingerprint,
                entry.no_progress_count,
                evidence_delta,
            ),
        )

    def before_call(
        self,
        tool_name: str,
        args: Mapping[str, Any] | None = None,
        *,
        declared_polling: bool = False,
        user_requested_wait: bool = False,
    ) -> GuardDecision:
        """Decide before side effects. A veto is not an execution result."""

        fingerprint = _digest({"tool": tool_name, "args": args or {}})
        entry = self._entries.get(fingerprint)
        if entry is None:
            entry = _JournalEntry(tool_name=tool_name, call_fingerprint=fingerprint)
            self._touch(entry)
            return self._decision(
                action=GuardAction.ALLOW,
                reason=GuardReason.FIRST_OBSERVATION,
                entry=entry,
            )

        if user_requested_wait or declared_polling:
            return self._decision(
                action=GuardAction.ALLOW,
                reason=GuardReason.POLLING_EXCEPTION,
                entry=entry,
                notice="explicit polling/wait policy permits this status check",
            )
        if entry.no_progress_count >= self.policy.hard_threshold:
            return self._decision(
                action=GuardAction.TERMINATE,
                reason=GuardReason.HARD_TERMINATION,
                entry=entry,
                notice="bounded no-progress threshold reached; stop honestly with evidence",
                terminal_status="blocked_no_progress",
            )
        if entry.no_progress_count >= self.policy.veto_threshold:
            return self._decision(
                action=GuardAction.VETO,
                reason=GuardReason.EXACT_CALL_VETO,
                entry=entry,
                notice="exact ineffective call vetoed before tool execution",
            )
        if entry.no_progress_count >= self.policy.warning_threshold:
            if entry.replan_count >= self.policy.replan_threshold:
                return self._decision(
                    action=GuardAction.TERMINATE,
                    reason=GuardReason.HARD_TERMINATION,
                    entry=entry,
                    notice="re-plan budget exhausted; stop honestly with evidence",
                    terminal_status="blocked_no_progress",
                )
            entry.replan_count += 1
            self._touch(entry)
            if entry.replan_count >= self.policy.replan_threshold:
                return self._decision(
                    action=GuardAction.REPLAN,
                    reason=GuardReason.REPLAN_REQUIRED,
                    entry=entry,
                    notice="re-plan required; repeated recovery cannot loop forever",
                )
            return self._decision(
                action=GuardAction.NOTICE,
                reason=GuardReason.REPEATED_NO_PROGRESS,
                entry=entry,
                notice="repeated ineffective pattern; provide a different strategy",
            )
        return self._decision(
            action=GuardAction.ALLOW,
            reason=GuardReason.REPEATED_NO_PROGRESS,
            entry=entry,
        )

    def record_result(
        self,
        tool_name: str,
        args: Mapping[str, Any] | None,
        result: Any,
        *,
        world_state_digest: str = "",
        evidence_count: int = 0,
        failure_code: str = "",
        result_category: str = "",
        declared_polling: bool = False,
        user_requested_wait: bool = False,
    ) -> GuardDecision:
        """Record one result and classify whether measurable progress occurred."""

        fingerprint = _digest({"tool": tool_name, "args": args or {}})
        entry = self._entries.get(fingerprint)
        if entry is None:
            entry = _JournalEntry(tool_name=tool_name, call_fingerprint=fingerprint)
            self._touch(entry)

        if not isinstance(evidence_count, int) or isinstance(evidence_count, bool) or evidence_count < 0:
            raise ValueError("evidence_count must be a non-negative integer")
        result_fingerprint = _digest(result)
        state_fingerprint = str(world_state_digest or "")
        evidence_delta = max(0, evidence_count - entry.evidence_count)
        first = not entry.last_result_fingerprint
        changed_result = bool(entry.last_result_fingerprint) and result_fingerprint != entry.last_result_fingerprint
        changed_state = bool(entry.last_world_state_fingerprint) and state_fingerprint != entry.last_world_state_fingerprint
        changed_evidence = evidence_delta > 0
        changed_failure = bool(entry.last_failure_code) and failure_code != entry.last_failure_code
        progress = first or changed_result or changed_state or changed_evidence or changed_failure

        entry.last_result_fingerprint = result_fingerprint
        entry.last_world_state_fingerprint = state_fingerprint
        entry.last_failure_code = failure_code
        entry.evidence_count = evidence_count

        if declared_polling or user_requested_wait or result_category in {"pending", "not_ready", "in_progress"}:
            self._touch(entry)
            return self._decision(
                action=GuardAction.ALLOW,
                reason=GuardReason.POLLING_EXCEPTION,
                entry=entry,
                evidence_delta=evidence_delta,
                notice="unchanged polling result is permitted by explicit policy",
            )

        if progress:
            entry.no_progress_count = 0
            entry.replan_count = 0
            self._touch(entry)
            return self._decision(
                action=GuardAction.ALLOW,
                reason=GuardReason.FIRST_OBSERVATION if first else GuardReason.PROGRESS_OBSERVED,
                entry=entry,
                evidence_delta=evidence_delta,
            )

        entry.no_progress_count += 1
        self._touch(entry)
        if entry.no_progress_count >= self.policy.hard_threshold:
            return self._decision(
                action=GuardAction.TERMINATE,
                reason=GuardReason.HARD_TERMINATION,
                entry=entry,
                evidence_delta=evidence_delta,
                notice="bounded no-progress threshold reached; stop honestly with evidence",
                terminal_status="blocked_no_progress",
            )
        if entry.no_progress_count >= self.policy.veto_threshold:
            return self._decision(
                action=GuardAction.VETO,
                reason=GuardReason.EXACT_CALL_VETO,
                entry=entry,
                evidence_delta=evidence_delta,
                notice="next exact call must be vetoed before side effects",
            )
        if entry.no_progress_count >= self.policy.warning_threshold:
            return self._decision(
                action=GuardAction.NOTICE,
                reason=GuardReason.REPEATED_NO_PROGRESS,
                entry=entry,
                evidence_delta=evidence_delta,
                notice="repeated ineffective pattern; switch strategy or re-plan",
            )
        return self._decision(
            action=GuardAction.ALLOW,
            reason=GuardReason.REPEATED_NO_PROGRESS,
            entry=entry,
            evidence_delta=evidence_delta,
        )

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        """Return a bounded, redacted journal snapshot for receipts/replay."""

        return tuple(
            {
                "tool_name": entry.tool_name,
                "call_fingerprint": entry.call_fingerprint,
                "no_progress_count": entry.no_progress_count,
                "replan_count": entry.replan_count,
                "evidence_count": entry.evidence_count,
                "last_failure_code": entry.last_failure_code,
            }
            for entry in self._entries.values()
        )

    def reset(self) -> None:
        self._entries.clear()
        self._sequence = 0
