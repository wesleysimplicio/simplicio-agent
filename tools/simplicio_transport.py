"""CLI-first transport for the Simplicio runtime.

The transport is deliberately small: the agent owns orchestration and this
module owns only the wire boundary to the runtime.  A normal call is always a
``simplicio <command>`` subprocess.  MCP is attempted only when that CLI
process is unavailable (the executable cannot be resolved or cannot be
started), never when a command returns an error, times out, or returns bad
data.

``TransportReceipt`` is the stable boundary for callers that need to retain
transport/error/fallback evidence.  ``SimplicioBridge`` supplies the legacy
typed value facade over it.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from tools import runtime_manager

logger = logging.getLogger(__name__)

RECEIPT_SCHEMA = "simplicio-transport/receipt/v1"
ERROR_SCHEMA = "simplicio-transport/error/v1"
FALLBACK_REASON_CLI_UNAVAILABLE = "cli_unavailable"
TRANSPORT_HEALTH_SCHEMA = "simplicio-transport/health/v1"


@dataclass(frozen=True)
class TransportError:
    """Uniform, serializable transport failure."""

    code: str
    message: str
    retryable: bool = False
    schema: str = ERROR_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransportReceipt:
    """Result of one transport attempt, including fallback evidence."""

    operation: str
    ok: bool
    value: Any = None
    error: Optional[TransportError] = None
    transport: str = "cli"
    fallback_reason: Optional[str] = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    schema: str = RECEIPT_SCHEMA
    elapsed_ms: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.error is not None:
            result["error"] = self.error.to_dict()
        return result

    @classmethod
    def success(
        cls,
        operation: str,
        value: Any = None,
        *,
        transport: str = "cli",
        fallback_reason: Optional[str] = None,
        request_id: Optional[str] = None,
        elapsed_ms: Optional[float] = None,
    ) -> "TransportReceipt":
        return cls(
            operation=operation,
            ok=True,
            value=value,
            transport=transport,
            fallback_reason=fallback_reason,
            request_id=request_id or uuid.uuid4().hex,
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def failure(
        cls,
        operation: str,
        error: TransportError,
        *,
        transport: str = "cli",
        fallback_reason: Optional[str] = None,
        request_id: Optional[str] = None,
        elapsed_ms: Optional[float] = None,
    ) -> "TransportReceipt":
        return cls(
            operation=operation,
            ok=False,
            error=error,
            transport=transport,
            fallback_reason=fallback_reason,
            request_id=request_id or uuid.uuid4().hex,
            elapsed_ms=elapsed_ms,
        )


class SimplicioTransport:
    """CLI-first transport with an opt-in injectable MCP fallback.

    ``mcp_call`` is intentionally injectable: applications may provide their
    already-connected MCP client without making the core depend on the MCP
    package.  It receives ``(operation, arguments)`` and may return a value,
    a ``TransportReceipt``, or raise.  ``mcp_command`` is the lower-level
    fallback for environments that want this class to own a stdio MCP
    process; it is not started unless the CLI attempt is unavailable.
    """

    _COMMANDS: dict[str, tuple[str, ...]] = {
        "gate": ("gate", "classify"),
        "checkpoint": ("checkpoint", "record"),
        "mechanical_edit": ("edit",),
        "orient": ("runtime", "map"),
        "recall": ("memory",),
        "ledger": ("ledger", "append"),
        "gitram": ("gitram",),
        # The runtime-native adapter supplies the tool name dynamically.  The
        # empty tuple is only a validation sentinel; `_runtime_tool_argv`
        # selects the concrete CLI command.
        "runtime_tool": (),
    }
    _MCP_TOOLS = {
        "gate": "simplicio_gate",
        "checkpoint": "simplicio_checkpoint",
        "mechanical_edit": "simplicio_edit",
        "orient": "simplicio_map",
        "recall": "simplicio_memory",
        "ledger": "simplicio_ledger",
        "gitram": "simplicio_gitram",
    }

    def __init__(
        self,
        *,
        cli_bin: Optional[str] = None,
        mcp_call: Optional[Callable[[str, dict[str, Any]], Any]] = None,
        mcp_command: Optional[Sequence[str]] = None,
        timeout_s: float = 20.0,
        fallback_ledger: Optional[Callable[[dict[str, Any]], Any]] = None,
        fallback_event_limit: int = 256,
    ) -> None:
        if fallback_event_limit < 1:
            raise ValueError("fallback_event_limit must be positive")
        self.cli_bin = cli_bin
        self.mcp_call = mcp_call
        self.mcp_command = tuple(mcp_command) if mcp_command else None
        self.timeout_s = timeout_s
        self.fallback_ledger = fallback_ledger
        self._lock = threading.Lock()
        self._calls = 0
        self._cli_calls = 0
        self._mcp_calls = 0
        self._failures = 0
        self._fallbacks = 0
        self._last_error: Optional[dict[str, Any]] = None
        self._last_fallback_reason: Optional[str] = None
        self._last_call_at: Optional[float] = None
        self._fallback_events: list[dict[str, Any]] = []
        self._fallback_event_limit = fallback_event_limit
        self._state = "ready"
        self._generation = 1
        self._started_at = time.time()
        self._closed_at: Optional[float] = None

    # -- lifecycle -----------------------------------------------------
    def lifecycle(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": "simplicio-transport/lifecycle/v1",
                "state": self._state,
                "generation": self._generation,
                "started_at": self._started_at,
                "closed_at": self._closed_at,
            }

    def start(self) -> dict[str, Any]:
        """Start (or restart) the stateless transport idempotently."""
        with self._lock:
            if self._state == "closed":
                self._state = "ready"
                self._generation += 1
                self._started_at = time.time()
                self._closed_at = None
            return {
                "schema": "simplicio-transport/lifecycle/v1",
                "state": self._state,
                "generation": self._generation,
                "started_at": self._started_at,
                "closed_at": self._closed_at,
            }

    def close(self) -> dict[str, Any]:
        """Close the transport idempotently; no subprocess is left running."""
        with self._lock:
            if self._state == "ready":
                self._state = "closed"
                self._closed_at = time.time()
            return {
                "schema": "simplicio-transport/lifecycle/v1",
                "state": self._state,
                "generation": self._generation,
                "started_at": self._started_at,
                "closed_at": self._closed_at,
            }

    # -- public operation methods -------------------------------------
    def gate(
        self,
        command: str,
        *,
        pattern_key: str = "",
        description: str = "",
        session_key: str = "",
    ) -> TransportReceipt:
        return self.call(
            "gate",
            command=command,
            pattern_key=pattern_key,
            description=description,
            session_key=session_key,
        )

    def checkpoint(
        self, label: str, *, workdir: str = "", extra: Optional[dict] = None
    ) -> TransportReceipt:
        return self.call("checkpoint", label=label, workdir=workdir, extra=extra)

    def mechanical_edit(self, plan: dict) -> TransportReceipt:
        return self.call("mechanical_edit", plan=plan)

    def orient(self, repo: str, *, fmt: str = "markdown") -> TransportReceipt:
        return self.call("orient", repo=repo, fmt=fmt)

    def recall(self, query: str, *, repo: str = "") -> TransportReceipt:
        return self.call("recall", query=query, repo=repo)

    def ledger(self, event: dict) -> TransportReceipt:
        return self.call("ledger", event=event)

    def gitram(self, subcommand: str, *args: str) -> TransportReceipt:
        """Dispatch a GitRAM cell-fabric operation.

        ``subcommand`` is one of ``dispatch`` / ``consensus`` / ``verify``; the
        remaining positional args are forwarded verbatim to ``simplicio gitram``.
        """
        full = [subcommand, *args]
        return self.call("gitram", _raw_args=full)

    def call_tool(
        self, name: str, arguments: Optional[dict[str, Any]] = None
    ) -> TransportReceipt:
        """Call one first-party Simplicio runtime tool by MCP name.

        This is the generic boundary used by the native-tool adapter.  Known
        tools use their concrete CLI command first; when that command is not
        available, the existing one-shot MCP fallback receives the exact MCP
        tool name and arguments.
        """
        return self.call(
            "runtime_tool",
            name=name,
            arguments=dict(arguments or {}),
        )

    def call(self, operation: str, **arguments: Any) -> TransportReceipt:
        """Execute one operation and return a uniform receipt."""
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        with self._lock:
            closed = self._state == "closed"
        if closed:
            return self._finish(
                TransportReceipt.failure(
                    operation,
                    TransportError("transport_closed", "Simplicio transport is closed"),
                    request_id=request_id,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )
            )
        if operation not in self._COMMANDS:
            return self._finish(
                TransportReceipt.failure(
                    operation,
                    TransportError(
                        "unknown_operation", f"unsupported operation: {operation}"
                    ),
                    request_id=request_id,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )
            )

        cli_result = self._call_cli(operation, arguments, request_id=request_id)
        if cli_result is not None:
            return self._finish(self._with_elapsed(cli_result, started))

        # ``None`` is reserved for CLI unavailability.  Command errors and
        # malformed output are receipts and therefore never reach this path.
        reason = FALLBACK_REASON_CLI_UNAVAILABLE
        with self._lock:
            self._fallbacks += 1
            self._last_fallback_reason = reason
        self._record_fallback(operation, request_id, reason)
        mcp_result = self._call_mcp(operation, arguments, request_id=request_id)
        if mcp_result is None:
            mcp_result = TransportReceipt.failure(
                operation,
                TransportError(
                    "mcp_unavailable", "CLI unavailable and MCP fallback is unavailable"
                ),
                transport="mcp",
                fallback_reason=reason,
                request_id=request_id,
            )
        elif mcp_result.fallback_reason is None:
            mcp_result = TransportReceipt(
                operation=mcp_result.operation,
                ok=mcp_result.ok,
                value=mcp_result.value,
                error=mcp_result.error,
                transport="mcp",
                fallback_reason=reason,
                request_id=request_id,
                elapsed_ms=mcp_result.elapsed_ms,
            )
        return self._finish(self._with_elapsed(mcp_result, started))

    def health(self) -> dict[str, Any]:
        """Return transport health suitable for status/doctor surfaces."""
        with self._lock:
            return {
                "schema": TRANSPORT_HEALTH_SCHEMA,
                "healthy": self._state == "ready"
                and (self._failures == 0 or self._calls == 0),
                "state": self._state,
                "generation": self._generation,
                "started_at": self._started_at,
                "closed_at": self._closed_at,
                "calls": self._calls,
                "cli_calls": self._cli_calls,
                "mcp_calls": self._mcp_calls,
                "failures": self._failures,
                "fallbacks": self._fallbacks,
                "last_error": self._last_error,
                "last_fallback_reason": self._last_fallback_reason,
                "last_call_at": self._last_call_at,
            }

    @property
    def fallback_events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(event) for event in self._fallback_events)

    # -- CLI -----------------------------------------------------------
    def _resolve_cli(self) -> Optional[str]:
        if self.cli_bin:
            return self.cli_bin
        path, _source = runtime_manager.resolve_kernel()
        return path

    def _call_cli(
        self, operation: str, args: dict[str, Any], *, request_id: str
    ) -> Optional[TransportReceipt]:
        cli_bin = self._resolve_cli()
        if not cli_bin:
            return None
        if operation == "runtime_tool":
            runtime_argv = self._runtime_tool_argv(args)
            # No concrete CLI mapping means this operation must use MCP when
            # configured; it is not a reason to execute a different command.
            if runtime_argv is None:
                return None
            argv, input_data = runtime_argv
        else:
            argv, input_data = self._argv(operation, args)
        started = time.monotonic()
        try:
            command = [cli_bin, *argv]
            if os.name == "nt" and Path(cli_bin).suffix.lower() in {".cmd", ".bat"}:
                command = ["cmd.exe", "/d", "/c", cli_bin, *argv]
            windows_flags = self._windows_flags()
            try:
                proc = subprocess.run(
                    command,
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    **windows_flags,
                )
            except OSError:
                # Some Windows hosts reject CREATE_NO_WINDOW for a batch
                # wrapper after another subprocess has changed console/job
                # state. The wrapper is still a valid CLI, so retry once
                # without cosmetic creation flags before declaring it absent.
                if not (
                    os.name == "nt"
                    and Path(cli_bin).suffix.lower() in {".cmd", ".bat"}
                    and windows_flags.get("creationflags")
                ):
                    raise
                logger.debug("retrying CLI wrapper without Windows hide flags")
                proc = subprocess.run(
                    command,
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                )
        except (FileNotFoundError, PermissionError) as exc:
            logger.debug("simplicio CLI unavailable: %s", exc)
            return None
        except OSError as exc:
            # A launch error is unavailability; an executed command's error
            # is handled below and must not trigger MCP fallback.
            logger.debug("simplicio CLI could not start: %s", exc)
            return None
        except subprocess.TimeoutExpired as exc:
            return TransportReceipt.failure(
                operation,
                TransportError("cli_timeout", str(exc), retryable=True),
                request_id=request_id,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        with self._lock:
            self._cli_calls += 1
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "CLI command failed").strip()[:500]
            return TransportReceipt.failure(
                operation,
                TransportError("cli_command_failed", message, retryable=False),
                request_id=request_id,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        raw = (proc.stdout or "").strip()
        if not raw:
            return TransportReceipt.failure(
                operation,
                TransportError(
                    "cli_empty_output",
                    "CLI returned empty output; refusing to infer success",
                    retryable=False,
                ),
                request_id=request_id,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            return TransportReceipt.failure(
                operation,
                TransportError(
                    "cli_invalid_json",
                    f"CLI returned invalid JSON: {exc}",
                    retryable=False,
                ),
                request_id=request_id,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        return TransportReceipt.success(
            operation,
            value,
            request_id=request_id,
            elapsed_ms=(time.monotonic() - started) * 1000,
        )

    @staticmethod
    def _windows_flags() -> dict[str, Any]:
        if os.name != "nt":
            return {}
        try:
            from hermes_cli._subprocess_compat import windows_hide_flags

            return {"creationflags": windows_hide_flags()}
        except Exception:
            return {}

    def _argv(
        self, operation: str, args: dict[str, Any]
    ) -> tuple[list[str], Optional[str]]:
        base = list(self._COMMANDS[operation])
        if operation == "gate":
            base += ["--action", str(args["command"]), "--json"]
        elif operation == "checkpoint":
            return base + ["--json"], json.dumps({
                "label": args["label"],
                "workdir": args.get("workdir", ""),
                **(args.get("extra") or {}),
            })
        elif operation == "mechanical_edit":
            base += [json.dumps(args["plan"]), "--json"]
        elif operation == "orient":
            base += [
                "--repo",
                str(args["repo"]),
                "--for-llm",
                str(args.get("fmt", "markdown")),
                "--json",
            ]
        elif operation == "recall":
            base += [str(args["query"]), "--json"]
            if args.get("repo"):
                base += ["--repo", str(args["repo"])]
        elif operation == "ledger":
            return base + ["--json"], json.dumps(args["event"])
        elif operation == "gitram":
            raw = args.get("_raw_args") or []
            return base + [str(a) for a in raw] + ["--json"], None
        return base, None

    @staticmethod
    def _runtime_tool_argv(
        args: dict[str, Any],
    ) -> Optional[tuple[list[str], Optional[str]]]:
        """Translate the bounded first-party MCP tools to CLI argv.

        Keep this table intentionally explicit.  A generic MCP tool name must
        never be guessed into an arbitrary subprocess command.
        """
        name = args.get("name")
        tool_args = args.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(tool_args, dict):
            return None

        if name == "simplicio_file_read":
            path = tool_args.get("path")
            if not isinstance(path, str) or not path:
                return None
            argv = ["file", "read", path, "--json"]
            repo = tool_args.get("repo")
            if isinstance(repo, str) and repo:
                argv += ["--repo", repo]
            for key, flag in (("start", "--start"), ("end", "--end"), ("max_bytes", "--max-bytes")):
                value = tool_args.get(key)
                if value is not None:
                    argv += [flag, str(value)]
            return argv, None

        if name == "simplicio_file_write":
            path = tool_args.get("path")
            content = tool_args.get("content")
            if not isinstance(path, str) or not path or not isinstance(content, str):
                return None
            argv = ["file", "write", path, "--content", content, "--json"]
            repo = tool_args.get("repo")
            if isinstance(repo, str) and repo:
                argv += ["--repo", repo]
            if tool_args.get("create_parents") is True:
                argv.append("--create-parents")
            return argv, None

        if name == "simplicio_edit":
            plan = tool_args.get("plan")
            if not isinstance(plan, str) or not plan:
                return None
            return ["edit", plan, "--json"], None

        if name == "simplicio_session_search":
            # The CLI exposes the common browse/discover/read shapes. Keep
            # scroll and extra filters on MCP so the adapter never silently
            # drops native session-search semantics.
            unsupported = {
                key
                for key in ("role_filter", "around_message_id", "window", "sort")
                if key in tool_args
            }
            if unsupported:
                return None

            if tool_args.get("session_id") is not None:
                session_id = tool_args.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    return None
                argv = ["session", "read", session_id]
            elif tool_args.get("query") is not None:
                query = tool_args.get("query")
                if not isinstance(query, str) or not query:
                    return None
                argv = ["session", "search", query]
            else:
                argv = ["session", "browse"]

            limit = tool_args.get("limit")
            if limit is not None:
                argv += ["--limit", str(limit)]
            profile = tool_args.get("profile")
            if profile is not None:
                if not isinstance(profile, str) or not profile:
                    return None
                argv += ["--profile", profile]
            argv.append("--json")
            return argv, None

        if name == "simplicio_exec":
            command = tool_args.get("command")
            if (
                not isinstance(command, str)
                or not command.strip()
                or any(char in command for char in ";&|><$" + chr(96) + "\x00\n\r")
            ):
                return None
            argv = ["exec", command.strip()]
            repo = tool_args.get("repo")
            if isinstance(repo, str) and repo:
                argv += ["--repo", repo]
            if "--json" not in command.split():
                argv.append("--json")
            return argv, None

        return None

    # -- MCP -----------------------------------------------------------
    def _call_mcp(
        self, operation: str, args: dict[str, Any], *, request_id: str
    ) -> Optional[TransportReceipt]:
        if self.mcp_call is not None:
            started = time.monotonic()
            try:
                value = self.mcp_call(operation, args)
                if isinstance(value, TransportReceipt):
                    with self._lock:
                        self._mcp_calls += 1
                    return value
                with self._lock:
                    self._mcp_calls += 1
                return TransportReceipt.success(
                    operation,
                    value,
                    transport="mcp",
                    request_id=request_id,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )
            except Exception as exc:
                return TransportReceipt.failure(
                    operation,
                    TransportError("mcp_call_failed", str(exc), retryable=True),
                    transport="mcp",
                    request_id=request_id,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )
        if not self.mcp_command:
            return None
        # A command-level fallback is intentionally one-shot. Persistent MCP
        # sessions belong to the explicit warm-mode adapter and must not
        # silently become the default execution channel.
        started = time.monotonic()
        mcp_arguments = self._mcp_arguments(operation, args)
        proc = None
        try:
            proc = subprocess.Popen(
                list(self.mcp_command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                **self._windows_flags(),
            )
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "simplicio-agent", "version": "1"},
                    },
                })
                + "\n"
            )
            proc.stdin.flush()
            init_line = proc.stdout.readline()
            if not init_line:
                raise OSError("MCP server closed during initialize")
            proc.stdin.write(
                json.dumps({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": (
                            args["name"]
                            if operation == "runtime_tool"
                            else self._MCP_TOOLS[operation]
                        ),
                        "arguments": mcp_arguments,
                    },
                })
                + "\n"
            )
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                raise OSError("MCP server closed during tools/call")
            frame = json.loads(line)
            if "error" in frame:
                raise RuntimeError(str(frame["error"]))
            value = frame.get("result", {})
            content = value.get("content") if isinstance(value, dict) else None
            if isinstance(content, list) and content and isinstance(content[0], dict):
                text_value = content[0].get("text")
                if isinstance(text_value, str):
                    value = json.loads(text_value)
            result = TransportReceipt.success(
                operation,
                value,
                transport="mcp",
                request_id=request_id,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
            with self._lock:
                self._mcp_calls += 1
            return result
        except (
            OSError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            return TransportReceipt.failure(
                operation,
                TransportError("mcp_unavailable", str(exc), retryable=True),
                transport="mcp",
                request_id=request_id,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        finally:
            if proc is not None:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass

    @staticmethod
    def _mcp_arguments(operation: str, args: dict[str, Any]) -> dict[str, Any]:
        """Map the CLI-shaped operation arguments to runtime MCP arguments."""
        if operation == "runtime_tool":
            arguments = args.get("arguments")
            return dict(arguments) if isinstance(arguments, dict) else {}
        if operation == "gate":
            return {"action": args["command"]}
        if operation == "checkpoint":
            return {
                "label": args["label"],
                "workdir": args.get("workdir", ""),
                **(args.get("extra") or {}),
            }
        if operation == "mechanical_edit":
            return {"plan": args["plan"]}
        if operation == "orient":
            return {"repo": args["repo"], "format": args.get("fmt", "markdown")}
        if operation == "recall":
            return {"query": args["query"], "repo": args.get("repo", "")}
        return {"event": args["event"]}

    def _record_fallback(self, operation: str, request_id: str, reason: str) -> None:
        event = {
            "schema": "simplicio-transport/fallback/v1",
            "operation": operation,
            "request_id": request_id,
            "reason": reason,
            "source": "simplicio_transport",
        }
        with self._lock:
            self._fallback_events.append(event)
            if len(self._fallback_events) > self._fallback_event_limit:
                del self._fallback_events[: -self._fallback_event_limit]
        if self.fallback_ledger is not None:
            try:
                self.fallback_ledger(event)
            except Exception as exc:
                logger.debug("failed to record transport fallback in ledger: %s", exc)

    def _finish(self, receipt: TransportReceipt) -> TransportReceipt:
        with self._lock:
            self._calls += 1
            self._last_call_at = time.time()
            if not receipt.ok:
                self._failures += 1
                self._last_error = receipt.error.to_dict() if receipt.error else None
        return receipt

    @staticmethod
    def _with_elapsed(receipt: TransportReceipt, started: float) -> TransportReceipt:
        if receipt.elapsed_ms is not None:
            return receipt
        return TransportReceipt(
            operation=receipt.operation,
            ok=receipt.ok,
            value=receipt.value,
            error=receipt.error,
            transport=receipt.transport,
            fallback_reason=receipt.fallback_reason,
            request_id=receipt.request_id,
            elapsed_ms=(time.monotonic() - started) * 1000,
        )


__all__ = [
    "ERROR_SCHEMA",
    "FALLBACK_REASON_CLI_UNAVAILABLE",
    "RECEIPT_SCHEMA",
    "SimplicioTransport",
    "TransportError",
    "TransportReceipt",
]
