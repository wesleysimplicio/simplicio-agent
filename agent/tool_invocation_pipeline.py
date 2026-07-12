"""Single lifecycle chokepoint for tool invocations.

The pipeline deliberately owns orchestration, not tool implementations.  It is
small enough to be used by both sequential and concurrent dispatchers and keeps
policy ordering observable for audit/evidence consumers.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


STAGES = (
    "resolve", "normalize", "authorize", "middleware", "classify", "guardrail",
    "action-gate", "checkpoint", "execute", "result-classification", "persist",
    "evidence", "emit",
)


@dataclass
class ToolInvocation:
    name: str
    args: dict[str, Any]
    tool_call_id: str = ""
    task_id: str = ""


@dataclass
class ToolInvocationOutcome:
    result: Any = None
    status: str = "success"
    error_type: str | None = None
    trace: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


class ToolInvocationPipeline:
    """Run one invocation through one ordered, auditable lifecycle.

    Hooks are optional and intentionally dependency-injected so this primitive
    can cover registry tools and agent-owned special tools without importing
    either implementation.  A hook may return a transformed value; returning
    ``None`` means "leave the current value unchanged".
    """

    def __init__(self, *, hooks: Mapping[str, Callable[..., Any]] | None = None):
        self.hooks = dict(hooks or {})

    def _call(self, stage: str, value: Any, **context: Any) -> Any:
        fn = self.hooks.get(stage)
        if fn is None:
            return value
        changed = fn(value, **context)
        return value if changed is None else changed

    def begin(self, invocation: ToolInvocation) -> tuple[ToolInvocation, list[str]]:
        """Run the non-executing front half for legacy dispatchers.

        Existing special tools still own their implementation, but they now
        enter the same chokepoint and receive the same resolve/normalize/
        authorize/middleware/classify/guardrail/action-gate/checkpoint trace.
        """
        trace = ["resolve", "normalize", "authorize", "middleware", "classify", "guardrail", "action-gate", "checkpoint"]
        args = invocation.args if isinstance(invocation.args, dict) else {}
        for stage in ("resolve", "normalize", "authorize", "middleware"):
            args = self._call(stage, args, invocation=invocation, name=invocation.name)
            if not isinstance(args, dict):
                raise TypeError(f"{stage} must return an object")
        category = self._call("classify", invocation.name, invocation=invocation, args=args)
        for stage in ("guardrail", "action-gate"):
            decision = self._call(stage, True, invocation=invocation, name=invocation.name, args=args, category=category)
            if decision is False or (isinstance(decision, dict) and not decision.get("allow", True)):
                raise PermissionError(f"tool blocked by {stage}")
        self._call("checkpoint", None, invocation=invocation, name=invocation.name, args=args, category=category)
        return ToolInvocation(invocation.name, args, invocation.tool_call_id, invocation.task_id), trace

    def complete(self, invocation: ToolInvocation, result: Any, trace: list[str], *, status: str = "success") -> ToolInvocationOutcome:
        """Run the common result/persistence/evidence/emit tail for legacy paths."""
        trace = list(trace) + ["execute", "result-classification", "persist", "evidence", "emit"]
        status = self._call("result-classification", status, invocation=invocation, result=result)
        self._call("persist", result, invocation=invocation, status=status)
        evidence = {"tool": invocation.name, "tool_call_id": invocation.tool_call_id, "status": status}
        evidence = self._call("evidence", evidence, invocation=invocation, result=result) or evidence
        self._call("emit", result, invocation=invocation, status=status, evidence=evidence)
        return ToolInvocationOutcome(result, status, None, trace, evidence)

    def run(self, invocation: ToolInvocation, execute: Callable[[str, dict[str, Any]], Any]) -> ToolInvocationOutcome:
        started = time.monotonic()
        trace: list[str] = []
        value: Any = invocation.args
        name = invocation.name
        try:
            trace.append("resolve")
            resolved = self._call("resolve", name, invocation=invocation)
            name = str(resolved)

            trace.append("normalize")
            value = self._call("normalize", value, invocation=invocation, name=name)
            if not isinstance(value, dict):
                raise TypeError("normalized tool arguments must be an object")

            for stage in ("authorize", "middleware"):
                trace.append(stage)
                value = self._call(stage, value, invocation=invocation, name=name)
                if not isinstance(value, dict):
                    raise TypeError(f"{stage} must return an object")

            trace.append("classify")
            category = self._call("classify", name, invocation=invocation, args=value)

            for stage in ("guardrail", "action-gate"):
                trace.append(stage)
                decision = self._call(stage, True, invocation=invocation, name=name, args=value, category=category)
                if decision is False or (isinstance(decision, dict) and not decision.get("allow", True)):
                    return self._blocked(name, value, trace, decision, started)

            trace.append("checkpoint")
            self._call("checkpoint", None, invocation=invocation, name=name, args=value, category=category)

            trace.append("execute")
            result = execute(name, value)

            trace.append("result-classification")
            status = self._call("result-classification", "success", invocation=invocation, name=name, args=value, result=result)
            if status not in {"success", "error", "cancelled"}:
                status = "success"

            trace.append("persist")
            self._call("persist", result, invocation=invocation, name=name, args=value, status=status)
            evidence = {
                "tool": name,
                "tool_call_id": invocation.tool_call_id,
                "task_id": invocation.task_id,
                "status": status,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "args_hash": hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest(),
            }
            trace.append("evidence")
            evidence = self._call("evidence", evidence, invocation=invocation, result=result) or evidence
            trace.append("emit")
            self._call("emit", result, invocation=invocation, status=status, evidence=evidence)
            return ToolInvocationOutcome(result, status, None, trace, evidence)
        except Exception as exc:
            status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "error"
            error_type = type(exc).__name__
            trace.extend(["result-classification", "persist", "evidence", "emit"])
            evidence = {"tool": name, "status": status, "error_type": error_type}
            self._call("persist", None, invocation=invocation, name=name, status=status, error=exc)
            self._call("evidence", evidence, invocation=invocation, error=exc)
            self._call("emit", None, invocation=invocation, status=status, evidence=evidence)
            return ToolInvocationOutcome(None, status, error_type, trace, evidence)

    def _blocked(self, name: str, args: dict[str, Any], trace: list[str], decision: Any, started: float) -> ToolInvocationOutcome:
        result = {"error": f"Tool '{name}' blocked", "status": "blocked"}
        trace.extend(["persist", "evidence", "emit"])
        evidence = {"tool": name, "status": "blocked", "duration_ms": int((time.monotonic() - started) * 1000)}
        self._call("persist", result, name=name, args=args, status="blocked", decision=decision)
        self._call("evidence", evidence, name=name, status="blocked", decision=decision)
        self._call("emit", result, name=name, status="blocked", evidence=evidence)
        return ToolInvocationOutcome(result, "blocked", "policy", trace, evidence)


def pipeline_for_agent(agent: Any) -> ToolInvocationPipeline:
    """Return the shared pipeline with agent hooks, preserving best-effort policy."""
    hooks = getattr(agent, "tool_invocation_pipeline_hooks", None)
    return ToolInvocationPipeline(hooks=hooks)
