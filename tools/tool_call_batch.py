"""Validated, ordered transport for local-model tool-call batches."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping


class SafetyClass(str, Enum):
    READ_ONLY = "read_only"
    MUTATION = "mutation"
    APPROVAL = "approval"
    TERMINAL = "terminal"
    DATA_DEPENDENT = "data_dependent"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    safety: SafetyClass = SafetyClass.READ_ONLY
    required_args: frozenset[str] = frozenset()
    allowed_args: frozenset[str] | None = None


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    call_id: str


@dataclass(frozen=True)
class BatchResult:
    call_id: str
    tool: str
    ok: bool
    value: Any = None
    error: str | None = None


class BatchValidationError(ValueError):
    """A model payload was rejected before any tool handler could run."""


def build_gbnf(registry: Mapping[str, ToolSpec]) -> str:
    """Return a deterministic grammar fragment for the frozen tool registry."""
    names = " | ".join(json.dumps(name, separators=(",", ":")) for name in sorted(registry))
    if not names:
        raise ValueError("tool registry must not be empty")
    return (
        "root ::= \"[\" ws call (ws \" , \" ws call)* ws \"]\"\n"
        "call ::= \"{\" ws \"tool\" ws \" : \" ws tool ws \",\" ws "
        "\"args\" ws \" : \" ws object ws \"}\"\n"
        f"tool ::= {names}\n"
        "object ::= \"{\" (string ws \" : \" ws value (ws \" , \" ws string ws \" : \" ws value)*)? ws \"}\""
    )


def _depth(value: Any, current: int = 0) -> int:
    if isinstance(value, dict):
        return max([current, *(_depth(v, current + 1) for v in value.values())])
    if isinstance(value, list):
        return max([current, *(_depth(v, current + 1) for v in value)])
    return current


def parse_tool_call_batch(
    payload: str | bytes | bytearray,
    registry: Mapping[str, ToolSpec],
    *,
    max_calls: int = 16,
    max_payload_bytes: int = 64 * 1024,
    max_depth: int = 12,
) -> tuple[ToolCall, ...]:
    """Parse and validate model JSON without invoking a handler."""
    if not registry:
        raise BatchValidationError("empty tool registry")
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if len(raw) > max_payload_bytes:
        raise BatchValidationError("payload exceeds byte limit")
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchValidationError("malformed JSON array") from exc
    if not isinstance(decoded, list) or not decoded:
        raise BatchValidationError("tool-call payload must be a non-empty array")
    if len(decoded) > max_calls:
        raise BatchValidationError("tool-call count exceeds limit")
    if _depth(decoded) > max_depth:
        raise BatchValidationError("payload nesting exceeds limit")

    calls: list[ToolCall] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise BatchValidationError(f"call {index} must be an object")
        unknown = set(item) - {"id", "tool", "args"}
        if unknown:
            raise BatchValidationError(f"call {index} has unknown fields")
        name = item.get("tool")
        args = item.get("args")
        if not isinstance(name, str) or name not in registry:
            raise BatchValidationError(f"call {index} has an unknown tool")
        if not isinstance(args, dict):
            raise BatchValidationError(f"call {index} args must be an object")
        spec = registry[name]
        missing = spec.required_args - args.keys()
        if missing:
            raise BatchValidationError(f"call {index} is missing required args")
        if spec.allowed_args is not None and set(args) - spec.allowed_args:
            raise BatchValidationError(f"call {index} has unknown args")
        call_id = item.get("id", str(index))
        if not isinstance(call_id, str) or not call_id:
            raise BatchValidationError(f"call {index} id must be a non-empty string")
        if call_id in seen_ids:
            raise BatchValidationError("duplicate call id")
        seen_ids.add(call_id)
        calls.append(ToolCall(name=name, args=dict(args), call_id=call_id))
    return tuple(calls)


def classify_batch(calls: tuple[ToolCall, ...], registry: Mapping[str, ToolSpec]) -> bool:
    """Allow parallel dispatch only for a mechanically read-only batch."""
    return len(calls) > 1 and all(registry[call.name].safety is SafetyClass.READ_ONLY for call in calls)


def execute_tool_call_batch(
    payload: str | bytes | bytearray,
    registry: Mapping[str, ToolSpec],
    handler: Callable[[ToolCall], Any],
    *,
    timeout_s: float = 30.0,
) -> tuple[BatchResult, ...]:
    """Validate, classify and execute, projecting results in source order."""
    calls = parse_tool_call_batch(payload, registry)
    parallel = classify_batch(calls, registry)
    results: list[BatchResult | None] = [None] * len(calls)

    def run(index: int, call: ToolCall) -> None:
        try:
            results[index] = BatchResult(call.call_id, call.name, True, value=handler(call))
        except Exception as exc:  # handler failures are bounded evidence, not parser escapes
            results[index] = BatchResult(call.call_id, call.name, False, error=type(exc).__name__)

    if parallel:
        with ThreadPoolExecutor(max_workers=len(calls), thread_name_prefix="tool-batch") as pool:
            futures = [pool.submit(run, index, call) for index, call in enumerate(calls)]
            try:
                for future in futures:
                    future.result(timeout=timeout_s)
            except TimeoutError:
                for future in futures:
                    future.cancel()
                raise BatchValidationError("parallel batch timed out")
    else:
        for index, call in enumerate(calls):
            run(index, call)
    return tuple(result for result in results if result is not None)
