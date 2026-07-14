"""Typed, auditable lifecycle for one tool invocation attempt.

The pipeline is intentionally narrow: it owns stage ordering, metadata
defaults, receipt/evidence production, and a serial executor adapter. Tool
implementations and existing executors stay outside this module.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol


StageName = Literal[
    "resolve",
    "normalize",
    "authorize",
    "classify",
    "guardrail",
    "action-gate",
    "checkpoint",
    "execute",
    "persist",
    "evidence",
]

STAGES: tuple[StageName, ...] = (
    "resolve",
    "normalize",
    "authorize",
    "classify",
    "guardrail",
    "action-gate",
    "checkpoint",
    "execute",
    "persist",
    "evidence",
)

_SAFE_STATUS = {"success", "error", "blocked", "cancelled"}
_DEFAULT_REDACTED_KEYS = frozenset({
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
})


class ToolExecutor(Protocol):
    def __call__(self, name: str, args: dict[str, Any]) -> Any: ...


class StageHook(Protocol):
    def __call__(self, value: Any, *, attempt: "ToolInvocationAttempt") -> Any: ...


class ReceiptWriter(Protocol):
    def __call__(self, receipt: "ToolInvocationReceipt") -> Any: ...


@dataclass(frozen=True)
class ToolInvocationMetadata:
    attempt_id: str = ""
    task_id: str = ""
    tool_call_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    api_request_id: str = ""
    actor: str = "agent"
    executor: str = "serial"
    classification: str = "unknown"
    status: str = "pending"
    blocked_by: str = ""
    error_type: str = ""
    error_message: str = ""
    duration_ms: int = 0
    receipt_id: str = ""
    receipt_written: bool = False
    external_result: bool = False
    evidence_version: str = "tool-invocation/v1"
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    args: dict[str, Any]
    tool_call_id: str = ""
    task_id: str = ""
    metadata: ToolInvocationMetadata = field(default_factory=ToolInvocationMetadata)


@dataclass(frozen=True)
class ToolDecision:
    allow: bool = True
    reason: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocationReceipt:
    attempt_id: str
    receipt_id: str
    tool: str
    status: str
    classification: str
    task_id: str
    tool_call_id: str
    duration_ms: int
    args_hash: str
    result_hash: str
    error_type: str = ""
    blocked_by: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocationOutcome:
    invocation: ToolInvocation
    result: Any = None
    status: str = "success"
    error_type: str | None = None
    trace: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    receipt: ToolInvocationReceipt | None = None


@dataclass(frozen=True)
class ToolInvocationAttempt:
    invocation: ToolInvocation
    metadata: ToolInvocationMetadata
    started_monotonic: float
    resolved_name: str
    normalized_args: dict[str, Any]
    classification: str = "unknown"
    guardrail_decision: ToolDecision = field(default_factory=ToolDecision)
    action_gate_decision: ToolDecision = field(default_factory=ToolDecision)
    result: Any = None
    status: str = "pending"
    error_type: str = ""
    error_message: str = ""
    trace: tuple[str, ...] = field(default_factory=tuple)
    receipt: ToolInvocationReceipt | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def with_trace(self, stage: StageName) -> "ToolInvocationAttempt":
        return replace(self, trace=self.trace + (stage,))

    def with_metadata(self, **changes: Any) -> "ToolInvocationAttempt":
        return replace(self, metadata=replace(self.metadata, **changes))


@dataclass
class SerialToolExecutorAdapter:
    """Small adapter so callers can preserve synchronous executors."""

    execute_fn: ToolExecutor
    label: str = "serial"
    executed_attempt_ids: list[str] = field(default_factory=list)

    def execute(self, attempt: ToolInvocationAttempt) -> Any:
        self.executed_attempt_ids.append(attempt.metadata.attempt_id)
        return self.execute_fn(attempt.resolved_name, dict(attempt.normalized_args))


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _coerce_mapping(value: Any, *, stage: StageName) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{stage} must return a mapping")
    return dict(value)


def _canonical_trace_prefix(
    trace: list[str] | tuple[str, ...],
) -> tuple[StageName, ...]:
    """Return a bounded canonical trace prefix for split completion.

    Callers may round-trip the trace across process boundaries, so completion
    normalizes the inbound value instead of trusting arbitrary ordering,
    duplication, or unknown stage names.
    """

    seen = set(trace)
    prefix: list[StageName] = []
    for stage in STAGES:
        if stage in seen:
            prefix.append(stage)
        if stage == "execute":
            break
    if "execute" not in seen and "persist" not in seen and "evidence" not in seen:
        prefix.append("execute")
    if "persist" in seen and "persist" not in prefix:
        prefix.append("persist")
    if "evidence" in seen and "evidence" not in prefix:
        prefix.append("evidence")
    return tuple(prefix)


def _coerce_decision(
    value: Any, *, stage: Literal["guardrail", "action-gate"]
) -> ToolDecision:
    if isinstance(value, ToolDecision):
        return value
    if value is False:
        return ToolDecision(allow=False, reason=stage)
    if value is True or value is None:
        return ToolDecision()
    if isinstance(value, Mapping):
        data = dict(value)
        return ToolDecision(
            allow=bool(data.get("allow", True)),
            reason=str(data.get("reason", "")),
            detail={k: v for k, v in data.items() if k not in {"allow", "reason"}},
        )
    raise TypeError(f"{stage} must return a decision-like value")


def _coerce_status(value: Any) -> str:
    if value is None or value == "":
        return "success"
    candidate = str(value)
    return candidate if candidate in _SAFE_STATUS else "error"


def _safe_text(value: Any, default: str = "") -> str:
    return str(value) if value is not None else default


def _redact_external_result(value: Any, redacted_keys: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            text_key = str(key)
            if text_key.lower() in redacted_keys:
                redacted[text_key] = "[REDACTED]"
            else:
                redacted[text_key] = _redact_external_result(child, redacted_keys)
        return redacted
    if isinstance(value, list):
        return [_redact_external_result(item, redacted_keys) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_external_result(item, redacted_keys) for item in value)
    return value


def _metadata_defaults(invocation: ToolInvocation) -> ToolInvocationMetadata:
    incoming = invocation.metadata
    args = invocation.args if isinstance(invocation.args, dict) else {}
    attempt_seed = {
        "name": invocation.name,
        "args": args,
        "task_id": invocation.task_id or incoming.task_id,
        "tool_call_id": invocation.tool_call_id or incoming.tool_call_id,
        "session_id": incoming.session_id,
        "turn_id": incoming.turn_id,
        "api_request_id": incoming.api_request_id,
    }
    attempt_id = incoming.attempt_id or _sha(attempt_seed)
    return replace(
        incoming,
        attempt_id=attempt_id,
        task_id=invocation.task_id or incoming.task_id,
        tool_call_id=invocation.tool_call_id or incoming.tool_call_id,
        actor=incoming.actor or "agent",
        executor=incoming.executor or "serial",
        classification=incoming.classification or "unknown",
        status=(
            incoming.status
            if incoming.status in _SAFE_STATUS or incoming.status == "pending"
            else "pending"
        ),
        evidence_version=incoming.evidence_version or "tool-invocation/v1",
        extras=dict(incoming.extras or {}),
    )


class ToolInvocationPipeline:
    """Single lifecycle chokepoint for one tool invocation."""

    def __init__(
        self,
        *,
        hooks: Mapping[StageName, StageHook] | None = None,
        receipt_writer: ReceiptWriter | None = None,
        redacted_result_keys: frozenset[str] | None = None,
    ):
        self.hooks = dict(hooks or {})
        self.receipt_writer = receipt_writer
        self.redacted_result_keys = (
            _DEFAULT_REDACTED_KEYS
            if redacted_result_keys is None
            else frozenset(str(key).lower() for key in redacted_result_keys)
        )
        self._receipts_by_attempt: dict[str, ToolInvocationReceipt] = {}
        self._receipt_errors: dict[str, BaseException] = {}
        self._receipts_written: set[str] = set()

    def _call(
        self, stage: StageName, value: Any, *, attempt: ToolInvocationAttempt
    ) -> Any:
        fn = self.hooks.get(stage)
        if fn is None:
            return value
        changed = fn(value, attempt=attempt)
        return value if changed is None else changed

    def begin(self, invocation: ToolInvocation) -> tuple[ToolInvocation, list[str]]:
        attempt = self._start_attempt(invocation)
        attempt = self._front_half(attempt)
        materialized = ToolInvocation(
            name=attempt.resolved_name,
            args=dict(attempt.normalized_args),
            tool_call_id=attempt.metadata.tool_call_id,
            task_id=attempt.metadata.task_id,
            metadata=attempt.metadata,
        )
        return materialized, list(attempt.trace)

    def complete(
        self,
        invocation: ToolInvocation,
        result: Any,
        trace: list[str],
        *,
        status: str = "success",
    ) -> ToolInvocationOutcome:
        trace = list(trace)
        if "execute" not in trace and "persist" not in trace:
            trace.append("execute")
        attempt = self._start_attempt(invocation)
        attempt = replace(
            attempt,
            resolved_name=invocation.name,
            normalized_args=dict(invocation.args),
            trace=_canonical_trace_prefix(trace),
            result=result,
            status=_coerce_status(status),
            classification=invocation.metadata.classification or "unknown",
        )
        attempt = self._persist_and_evidence(attempt)
        final_invocation = ToolInvocation(
            name=attempt.resolved_name,
            args=dict(attempt.normalized_args),
            tool_call_id=attempt.metadata.tool_call_id,
            task_id=attempt.metadata.task_id,
            metadata=attempt.metadata,
        )
        return ToolInvocationOutcome(
            invocation=final_invocation,
            result=attempt.result,
            status=attempt.status,
            error_type=attempt.error_type or None,
            trace=list(attempt.trace),
            evidence=dict(attempt.evidence),
            receipt=attempt.receipt,
        )

    def run(
        self,
        invocation: ToolInvocation,
        execute: ToolExecutor | SerialToolExecutorAdapter,
    ) -> ToolInvocationOutcome:
        adapter = (
            execute
            if isinstance(execute, SerialToolExecutorAdapter)
            else SerialToolExecutorAdapter(execute_fn=execute)
        )
        attempt = self._start_attempt(invocation).with_metadata(
            executor=adapter.label or "serial"
        )
        try:
            attempt = self._front_half(attempt)
            if (
                attempt.status == "blocked"
                or not attempt.guardrail_decision.allow
                or not attempt.action_gate_decision.allow
            ):
                final_invocation = ToolInvocation(
                    name=attempt.resolved_name,
                    args=dict(attempt.normalized_args),
                    tool_call_id=attempt.metadata.tool_call_id,
                    task_id=attempt.metadata.task_id,
                    metadata=attempt.metadata,
                )
                return ToolInvocationOutcome(
                    invocation=final_invocation,
                    result=attempt.result,
                    status=attempt.status,
                    error_type=attempt.error_type or None,
                    trace=list(attempt.trace),
                    evidence=dict(attempt.evidence),
                    receipt=attempt.receipt,
                )
            attempt = attempt.with_trace("execute")
            result = adapter.execute(attempt)
            attempt = replace(attempt, result=result, status="success")
            attempt = self._persist_and_evidence(attempt)
        except KeyboardInterrupt as exc:
            attempt = replace(
                attempt,
                status="cancelled",
                error_type=type(exc).__name__,
                error_message=_safe_text(exc),
                result=None,
            )
            attempt = self._persist_and_evidence(attempt)
        except Exception as exc:
            attempt = replace(
                attempt,
                status="cancelled" if isinstance(exc, KeyboardInterrupt) else "error",
                error_type=type(exc).__name__,
                error_message=_safe_text(exc),
                result=None,
            )
            if "persist" not in attempt.trace:
                attempt = self._persist_and_evidence(attempt)
        final_invocation = ToolInvocation(
            name=attempt.resolved_name,
            args=dict(attempt.normalized_args),
            tool_call_id=attempt.metadata.tool_call_id,
            task_id=attempt.metadata.task_id,
            metadata=attempt.metadata,
        )
        return ToolInvocationOutcome(
            invocation=final_invocation,
            result=attempt.result,
            status=attempt.status,
            error_type=attempt.error_type or None,
            trace=list(attempt.trace),
            evidence=dict(attempt.evidence),
            receipt=attempt.receipt,
        )

    def _start_attempt(self, invocation: ToolInvocation) -> ToolInvocationAttempt:
        args = invocation.args if isinstance(invocation.args, dict) else {}
        materialized = ToolInvocation(
            name=_safe_text(invocation.name),
            args=dict(args),
            tool_call_id=invocation.tool_call_id,
            task_id=invocation.task_id,
            metadata=_metadata_defaults(invocation),
        )
        return ToolInvocationAttempt(
            invocation=materialized,
            metadata=materialized.metadata,
            started_monotonic=time.monotonic(),
            resolved_name=materialized.name,
            normalized_args=dict(materialized.args),
        )

    def _front_half(self, attempt: ToolInvocationAttempt) -> ToolInvocationAttempt:
        attempt = attempt.with_trace("resolve")
        resolved_name = self._call("resolve", attempt.resolved_name, attempt=attempt)
        attempt = replace(attempt, resolved_name=_safe_text(resolved_name))

        attempt = attempt.with_trace("normalize")
        normalized = self._call(
            "normalize", dict(attempt.normalized_args), attempt=attempt
        )
        attempt = replace(
            attempt, normalized_args=_coerce_mapping(normalized, stage="normalize")
        )

        attempt = attempt.with_trace("authorize")
        authorized = self._call(
            "authorize", dict(attempt.normalized_args), attempt=attempt
        )
        attempt = replace(
            attempt, normalized_args=_coerce_mapping(authorized, stage="authorize")
        )

        attempt = attempt.with_trace("classify")
        classification = self._call(
            "classify", attempt.metadata.classification, attempt=attempt
        )
        attempt = replace(
            attempt, classification=_safe_text(classification, "unknown")
        ).with_metadata(classification=_safe_text(classification, "unknown"))

        attempt = attempt.with_trace("guardrail")
        guardrail = _coerce_decision(
            self._call("guardrail", ToolDecision(), attempt=attempt),
            stage="guardrail",
        )
        attempt = replace(attempt, guardrail_decision=guardrail)
        if not guardrail.allow:
            return self._blocked_attempt(attempt, "guardrail", guardrail)

        attempt = attempt.with_trace("action-gate")
        action_gate = _coerce_decision(
            self._call("action-gate", ToolDecision(), attempt=attempt),
            stage="action-gate",
        )
        attempt = replace(attempt, action_gate_decision=action_gate)
        if not action_gate.allow:
            return self._blocked_attempt(attempt, "action-gate", action_gate)

        attempt = attempt.with_trace("checkpoint")
        self._call("checkpoint", None, attempt=attempt)
        return attempt

    def _blocked_attempt(
        self,
        attempt: ToolInvocationAttempt,
        blocked_by: str,
        decision: ToolDecision,
    ) -> ToolInvocationAttempt:
        return self._persist_and_evidence(
            replace(
                attempt,
                status="blocked",
                error_type="policy",
                error_message=decision.reason or blocked_by,
            ).with_metadata(blocked_by=blocked_by)
        )

    def _persist_and_evidence(
        self, attempt: ToolInvocationAttempt
    ) -> ToolInvocationAttempt:
        if "persist" not in attempt.trace:
            attempt = attempt.with_trace("persist")
        duration_ms = max(0, int((time.monotonic() - attempt.started_monotonic) * 1000))
        status = _coerce_status(attempt.status)
        meta = replace(
            attempt.metadata,
            status=status,
            duration_ms=duration_ms,
            error_type=attempt.error_type,
            error_message=attempt.error_message,
        )
        attempt = replace(attempt, status=status, metadata=meta)
        try:
            persist_payload = self._call("persist", attempt.result, attempt=attempt)
            if persist_payload is not None and persist_payload is not attempt.result:
                attempt = replace(attempt, result=persist_payload)
        except KeyboardInterrupt as exc:
            attempt = self._mark_finalization_error(attempt, exc, "cancelled")
        except Exception as exc:
            attempt = self._mark_finalization_error(attempt, exc, "error")

        receipt = None
        try:
            receipt = self._write_receipt_once(attempt)
        except KeyboardInterrupt as exc:
            attempt = self._mark_finalization_error(attempt, exc, "cancelled")
            receipt = self._receipts_by_attempt.get(attempt.metadata.attempt_id)
        except Exception as exc:
            attempt = self._mark_finalization_error(attempt, exc, "error")
            receipt = self._receipts_by_attempt.get(attempt.metadata.attempt_id)
        attempt = replace(attempt, receipt=receipt).with_metadata(
            receipt_id=receipt.receipt_id if receipt else "",
            receipt_written=bool(
                receipt and receipt.receipt_id in self._receipts_written
            ),
        )

        if "evidence" not in attempt.trace:
            attempt = attempt.with_trace("evidence")
        evidence = self._default_evidence(attempt)
        try:
            overridden = self._call("evidence", evidence, attempt=attempt)
            evidence = (
                evidence
                if overridden is None
                else _coerce_mapping(overridden, stage="evidence")
            )
        except KeyboardInterrupt as exc:
            attempt = self._mark_finalization_error(attempt, exc, "cancelled")
            evidence = self._default_evidence(attempt)
        except Exception as exc:
            attempt = self._mark_finalization_error(attempt, exc, "error")
            evidence = self._default_evidence(attempt)
        receipt_error = self._receipt_errors.get(attempt.metadata.attempt_id)
        if receipt_error is not None:
            evidence = dict(evidence)
            evidence["receipt_error_type"] = type(receipt_error).__name__
            evidence["receipt_error_message"] = _safe_text(receipt_error)
        return replace(attempt, evidence=evidence)

    @staticmethod
    def _mark_finalization_error(
        attempt: ToolInvocationAttempt, exc: BaseException, status: str
    ) -> ToolInvocationAttempt:
        status = status if status in _SAFE_STATUS else "error"
        metadata = replace(
            attempt.metadata,
            status=status,
            error_type=type(exc).__name__,
            error_message=_safe_text(exc),
        )
        return replace(
            attempt,
            status=status,
            error_type=type(exc).__name__,
            error_message=_safe_text(exc),
            metadata=metadata,
        )

    def _write_receipt_once(
        self, attempt: ToolInvocationAttempt
    ) -> ToolInvocationReceipt:
        args_hash = _sha(attempt.normalized_args)
        result_hash = _sha(attempt.result)
        attempt_id = attempt.metadata.attempt_id
        existing = self._receipts_by_attempt.get(attempt_id)
        if existing is not None:
            return existing
        receipt_id = _sha({
            "attempt_id": attempt_id,
            "status": attempt.status,
            "args_hash": args_hash,
            "result_hash": result_hash,
        })
        receipt = ToolInvocationReceipt(
            attempt_id=attempt_id,
            receipt_id=receipt_id,
            tool=attempt.resolved_name,
            status=attempt.status,
            classification=attempt.classification,
            task_id=attempt.metadata.task_id,
            tool_call_id=attempt.metadata.tool_call_id,
            duration_ms=max(
                0, int((time.monotonic() - attempt.started_monotonic) * 1000)
            ),
            args_hash=args_hash,
            result_hash=result_hash,
            error_type=attempt.error_type,
            blocked_by=attempt.metadata.blocked_by,
            meta={
                "actor": attempt.metadata.actor,
                "executor": attempt.metadata.executor,
                "session_id": attempt.metadata.session_id,
                "turn_id": attempt.metadata.turn_id,
                "api_request_id": attempt.metadata.api_request_id,
            },
        )
        self._receipts_by_attempt[attempt_id] = receipt
        try:
            if self.receipt_writer is not None:
                self.receipt_writer(receipt)
            self._receipts_written.add(receipt.receipt_id)
        except BaseException as exc:
            self._receipt_errors[attempt_id] = exc
            raise
        return receipt

    def _default_evidence(self, attempt: ToolInvocationAttempt) -> dict[str, Any]:
        external_result = bool(attempt.metadata.external_result)
        evidence_result = copy.deepcopy(attempt.result)
        if external_result:
            evidence_result = _redact_external_result(
                evidence_result, self.redacted_result_keys
            )
        return {
            "version": attempt.metadata.evidence_version,
            "attempt_id": attempt.metadata.attempt_id,
            "tool": attempt.resolved_name,
            "tool_call_id": attempt.metadata.tool_call_id,
            "task_id": attempt.metadata.task_id,
            "status": attempt.status,
            "classification": attempt.classification,
            "duration_ms": attempt.metadata.duration_ms,
            "trace": list(attempt.trace),
            "blocked_by": attempt.metadata.blocked_by,
            "error_type": attempt.error_type,
            "error_message": attempt.error_message,
            "receipt_id": attempt.receipt.receipt_id if attempt.receipt else "",
            "external_result": external_result,
            "result": evidence_result,
            "meta": dict(attempt.metadata.extras or {}),
        }


def pipeline_for_agent(
    agent: Any, tool_name: str | None = None
) -> ToolInvocationPipeline:
    """Return the shared pipeline with agent-owned hook overrides.

    tool_name is accepted for call-site compatibility and future per-tool
    hooks; the shared pipeline is intentionally agent-scoped today.
    """

    del tool_name
    hooks = getattr(agent, "tool_invocation_pipeline_hooks", None)
    receipt_writer = getattr(agent, "tool_invocation_receipt_writer", None)
    return ToolInvocationPipeline(hooks=hooks, receipt_writer=receipt_writer)
