"""Runtime-first adapters for Hermes' native execution tools.

The agent still owns tool schemas and orchestration, but a native tool call
must give Simplicio Runtime the first opportunity to execute it.  This module
contains only explicit, typed adapters; it never guesses a runtime command.

When parity is missing or the managed runtime is unavailable, the result is a
structured capability gap.  Callers may then use the existing native handler,
but the gap is observable in the middleware trace and logs.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tools.simplicio_transport import SimplicioTransport, TransportReceipt
from tools import runtime_manager

logger = logging.getLogger(__name__)

RUNTIME_NATIVE_SCHEMA = "simplicio-agent/runtime-native/v1"
RUNTIME_GAP_MARKER = "UNVERIFIED| runtime capability gap"

# These are executable native tools.  Reasoning, delegation, provider, and
# UI-only tools are deliberately outside this set and do not create a fake
# runtime gap when they are dispatched.
RUNTIME_NATIVE_TOOLS = frozenset({
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "terminal",
    "read_terminal",
    "todo",
    "session_search",
    "memory",
})


@dataclass(frozen=True)
class RuntimeNativeDispatch:
    """Outcome of the Runtime-first attempt."""

    tool_name: str
    status: str  # executed | blocked | gap | not_applicable
    result: Any = None
    runtime_tool: Optional[str] = None
    receipt: Optional[TransportReceipt] = None
    reason: Optional[str] = None

    @property
    def handled(self) -> bool:
        return self.status in {"executed", "blocked"}

    def trace(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_NATIVE_SCHEMA,
            "tool": self.tool_name,
            "runtime_tool": self.runtime_tool,
            "status": self.status,
            "reason": self.reason,
            "transport": self.receipt.transport if self.receipt else None,
            "request_id": self.receipt.request_id if self.receipt else None,
        }


def is_runtime_native_tool(tool_name: str) -> bool:
    """Return whether *tool_name* is an executable native tool we supervise."""
    return tool_name in RUNTIME_NATIVE_TOOLS


def dispatch_native_tool(
    tool_name: str,
    arguments: Optional[dict[str, Any]] = None,
    *,
    task_id: str = "default",
    transport: Optional[SimplicioTransport] = None,
) -> RuntimeNativeDispatch:
    """Attempt one native tool through Simplicio Runtime first."""
    args = dict(arguments or {})
    if not is_runtime_native_tool(tool_name):
        return RuntimeNativeDispatch(tool_name, "not_applicable", reason="not_runtime_native")

    gate = _gate_mutation(tool_name, args, task_id)
    if gate is not None:
        return gate

    route = _build_route(tool_name, args, task_id)
    if route is None:
        return _gap(tool_name, "no_runtime_parity")
    if isinstance(route, RuntimeNativeDispatch):
        return route

    runtime_transport = transport or _new_runtime_transport()
    if runtime_transport is None:
        runtime_tool = getattr(route, "runtime_tool", None)
        return _gap(tool_name, "runtime_unavailable", runtime_tool=runtime_tool)
    if isinstance(route, _WriteRoute):
        return _execute_write_route(route, runtime_transport, tool_name)

    runtime_tool, runtime_args, decode = route

    try:
        receipt = runtime_transport.call_tool(runtime_tool, runtime_args)
    except Exception as exc:  # transport boundary must not break native recovery
        return _gap(tool_name, "runtime_transport_exception", runtime_tool=runtime_tool, detail=str(exc))

    if not receipt.ok:
        return _gap(
            tool_name,
            "runtime_call_failed",
            runtime_tool=runtime_tool,
            receipt=receipt,
            detail=receipt.error.message if receipt.error else None,
        )

    # A zero-token mechanical edit is only successful when the Runtime
    # explicitly acknowledges that it applied the plan.  A zero exit status,
    # empty JSON object, or unrelated JSON must never be turned into a
    # fabricated native-tool success (F2/#20, ADR-0020).
    if runtime_tool == "simplicio_edit" and not _edit_acknowledged(receipt.value):
        return _gap(
            tool_name,
            "runtime_edit_unacknowledged",
            runtime_tool=runtime_tool,
            receipt=receipt,
        )

    try:
        result = decode(receipt.value)
    except Exception as exc:
        return _gap(
            tool_name,
            "runtime_result_invalid",
            runtime_tool=runtime_tool,
            receipt=receipt,
            detail=str(exc),
        )

    if runtime_tool == "simplicio_edit":
        _emit_mechanical_edit_event(str(args.get("path") or ""))

    return RuntimeNativeDispatch(
        tool_name,
        "executed",
        result=result,
        runtime_tool=runtime_tool,
        receipt=receipt,
    )


def _gate_mutation(
    tool_name: str, args: dict[str, Any], task_id: str
) -> Optional[RuntimeNativeDispatch]:
    """Gate file mutations before resolving or invoking a Runtime edit."""
    if tool_name not in {"write_file", "patch"}:
        return None
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return None
    action = f"{tool_name} {path}"
    try:
        from tools.kernel_binding import evaluate_action_gate

        block = evaluate_action_gate(
            action,
            pattern_key=tool_name,
            description=f"native {tool_name} mutation",
            session_key=task_id,
        )
    except Exception as exc:
        return _gap(
            tool_name,
            "runtime_action_gate_exception",
            runtime_tool="simplicio_gate",
            detail=str(exc),
        )
    if block is None:
        return None
    message = block.get("message") if isinstance(block, dict) else str(block)
    return RuntimeNativeDispatch(
        tool_name,
        "blocked",
        result=_json_error(message or "blocked by runtime action gate"),
        runtime_tool="simplicio_gate",
        reason="runtime_action_gate",
    )


def _new_runtime_transport() -> Optional[SimplicioTransport]:
    kernel_bin, _source = runtime_manager.resolve_kernel()
    if not kernel_bin:
        return None
    return SimplicioTransport(
        cli_bin=kernel_bin,
        mcp_command=(kernel_bin, "serve", "--mcp", "--stdio"),
    )


def _build_route(tool_name: str, args: dict[str, Any], task_id: str):
    repo = _repo_for_task(task_id)

    if tool_name == "read_file":
        path = args.get("path")
        if not isinstance(path, str) or not path:
            return _gap(tool_name, "invalid_path")
        try:
            offset = max(int(args.get("offset", 1)), 1)
            limit = max(int(args.get("limit", 500)), 1)
        except (TypeError, ValueError):
            return _gap(tool_name, "invalid_pagination")
        resolved = _resolve_task_path(path, task_id)
        try:
            from agent.file_safety import get_read_block_error

            blocked = get_read_block_error(str(resolved))
        except Exception:
            blocked = None
        if blocked:
            return RuntimeNativeDispatch(tool_name, "blocked", result=_json_error(blocked), reason="native_read_guard")
        return (
            "simplicio_file_read",
            {
                "path": str(resolved),
                "start": offset,
                "end": offset + limit - 1,
                "repo": repo,
            },
            lambda value: _decode_runtime_read(value, offset),
        )

    if tool_name in {"write_file", "patch"}:
        path = args.get("path")
        if not isinstance(path, str) or not path:
            return _gap(tool_name, "invalid_path")
        guard = _write_guard(path, task_id, bool(args.get("cross_profile", False)))
        if guard:
            return RuntimeNativeDispatch(tool_name, "blocked", result=_json_error(guard), reason="native_write_guard")
        if tool_name == "patch":
            return _build_patch_route(args, task_id)
        return _build_write_route(args, task_id)

    # Runtime has no exact parity for these surfaces yet.  They still produce
    # an explicit capability receipt before the existing native handler runs.
    return None


def _build_patch_route(args: dict[str, Any], task_id: str):
    if args.get("mode", "replace") != "replace":
        return None
    old_string = args.get("old_string")
    new_string = args.get("new_string")
    path = args.get("path")
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return _gap("patch", "invalid_replace_arguments")
    resolved = _resolve_task_path(path, task_id)
    operation = {
        "op": "replace_all" if bool(args.get("replace_all", False)) else "replace",
        "find": old_string,
        "with": new_string,
    }
    plan = {"file": str(resolved), "operations": [operation]}
    return (
        "simplicio_edit",
        {"plan": json.dumps(plan, ensure_ascii=False)},
        lambda _value: _json_success([str(resolved)], include_bytes=False),
    )


def _build_write_route(args: dict[str, Any], task_id: str):
    path = args.get("path")
    content = args.get("content")
    if not isinstance(content, str):
        return _gap("write_file", "invalid_content")
    resolved = _resolve_task_path(path, task_id)
    if not resolved.is_file():
        # `simplicio edit` is intentionally mechanical and cannot create
        # parent directories/files.  Keep the native create path explicit.
        return _gap("write_file", "runtime_edit_does_not_create_files", runtime_tool="simplicio_edit")

    # A full write is represented as a deterministic replace plan.  Read the
    # old body through Runtime as part of the same route; this prevents a
    # native read→native write bypass for existing files.
    return _WriteRoute(
        runtime_tool="simplicio_file_read",
        runtime_args={
            "path": str(resolved),
            "repo": _repo_for_task(task_id),
            "max_bytes": 16 * 1024 * 1024,
        },
        path=str(resolved),
        content=content,
    )


@dataclass(frozen=True)
class _WriteRoute:
    runtime_tool: str
    runtime_args: dict[str, Any]
    path: str
    content: str


def _execute_write_route(route: _WriteRoute, transport: SimplicioTransport, tool_name: str):
    read_receipt = transport.call_tool(route.runtime_tool, route.runtime_args)
    if not read_receipt.ok:
        return _gap(
            tool_name,
            "runtime_prewrite_read_failed",
            runtime_tool=route.runtime_tool,
            receipt=read_receipt,
        )
    value = _json_value(read_receipt.value)
    if not isinstance(value, dict) or not isinstance(value.get("content"), str):
        return _gap(tool_name, "runtime_prewrite_read_invalid", runtime_tool=route.runtime_tool, receipt=read_receipt)
    if value.get("truncated"):
        return _gap(tool_name, "runtime_prewrite_read_truncated", runtime_tool=route.runtime_tool, receipt=read_receipt)

    old_content = value["content"]
    if old_content:
        op = {"op": "replace", "find": old_content, "with": route.content}
    else:
        op = {"op": "append", "text": route.content}
    plan = {"file": route.path, "operations": [op]}
    edit_receipt = transport.call_tool(
        "simplicio_edit", {"plan": json.dumps(plan, ensure_ascii=False)}
    )
    if not edit_receipt.ok:
        return _gap(tool_name, "runtime_edit_failed", runtime_tool="simplicio_edit", receipt=edit_receipt)
    if not _edit_acknowledged(edit_receipt.value):
        return _gap(
            tool_name,
            "runtime_edit_unacknowledged",
            runtime_tool="simplicio_edit",
            receipt=edit_receipt,
        )
    _emit_mechanical_edit_event(route.path)
    return RuntimeNativeDispatch(
        tool_name,
        "executed",
        result=_json_success([route.path], include_bytes=True, content=route.content),
        runtime_tool="simplicio_edit",
        receipt=edit_receipt,
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _edit_acknowledged(value: Any) -> bool:
    """Return whether a Runtime edit response proves the plan was applied."""
    payload = _json_value(value)
    if not isinstance(payload, dict):
        return False
    if payload.get("applied") is True:
        return True
    return str(payload.get("status", "")).strip().lower() in {
        "ok",
        "applied",
        "success",
    }


def _emit_mechanical_edit_event(path: str) -> None:
    """Emit bounded F2 telemetry without coupling tool dispatch to logging."""
    try:
        from tools.kernel_binding import emit_savings_event

        emit_savings_event("mechanical_edit", "applied", path[:300])
    except Exception as exc:  # telemetry must never affect the edit result
        logger.debug("mechanical edit telemetry unavailable: %s", exc)


def _decode_runtime_read(value: Any, offset: int) -> str:
    payload = _json_value(value)
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
        raise ValueError("simplicio_file_read returned no content field")
    content = payload["content"]
    numbered = []
    for index, line in enumerate(content.splitlines(), start=offset):
        numbered.append(f"{index}|{line}")
    if content.endswith("\n"):
        rendered = "\n".join(numbered) + ("\n" if numbered else "")
    else:
        rendered = "\n".join(numbered)
    result = {
        "content": rendered,
        "total_lines": payload.get("total_lines", len(numbered)),
        "file_size": payload.get("file_size", payload.get("bytes", 0)),
        "truncated": bool(payload.get("truncated", False)),
    }
    if result["truncated"]:
        end = offset + len(numbered)
        result["hint"] = f"Use offset={end + 1} to continue reading"
    return json.dumps(result, ensure_ascii=False)


def _json_success(paths: list[str], *, include_bytes: bool, content: str = "") -> str:
    result: dict[str, Any] = {
        "success": True,
        "files_modified": paths,
        "resolved_path": paths[0] if len(paths) == 1 else None,
    }
    if include_bytes:
        result["bytes_written"] = len(content.encode("utf-8"))
    return json.dumps({key: value for key, value in result.items() if value is not None}, ensure_ascii=False)


def _json_error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _repo_for_task(task_id: str) -> str:
    try:
        from tools.file_tools import _resolve_base_dir

        return str(_resolve_base_dir(task_id))
    except Exception:
        return os.environ.get("TERMINAL_CWD") or os.getcwd()


def _resolve_task_path(path: str, task_id: str) -> Path:
    try:
        from tools.file_tools import _resolve_path_for_task

        return _resolve_path_for_task(path, task_id)
    except Exception:
        candidate = Path(path).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (Path(_repo_for_task(task_id)) / candidate).resolve()


def _write_guard(path: str, task_id: str, cross_profile: bool) -> Optional[str]:
    try:
        from tools.file_tools import _check_sensitive_path, _check_cross_profile_path

        sensitive = _check_sensitive_path(path, task_id)
        if sensitive:
            return sensitive
        if not cross_profile:
            return _check_cross_profile_path(path, task_id)
    except Exception:
        # Runtime sandboxing remains the final boundary if the compatibility
        # guard cannot be imported in a minimal installation.
        return None
    return None


def _gap(
    tool_name: str,
    reason: str,
    *,
    runtime_tool: Optional[str] = None,
    receipt: Optional[TransportReceipt] = None,
    detail: Optional[str] = None,
) -> RuntimeNativeDispatch:
    suffix = f": {detail}" if detail else ""
    message = f"{RUNTIME_GAP_MARKER}: tool={tool_name}; reason={reason}{suffix}"
    logger.warning(message)
    return RuntimeNativeDispatch(
        tool_name,
        "gap",
        runtime_tool=runtime_tool,
        receipt=receipt,
        reason=reason,
    )


__all__ = [
    "RUNTIME_GAP_MARKER",
    "RUNTIME_NATIVE_SCHEMA",
    "RUNTIME_NATIVE_TOOLS",
    "RuntimeNativeDispatch",
    "dispatch_native_tool",
    "is_runtime_native_tool",
]
