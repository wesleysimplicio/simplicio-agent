"""Programmatic Agent -> Simplicio Runtime bridge.

The Agent owns orchestration; this module owns the narrow command boundary.
Runtime commands are sent through tools.simplicio_transport.SimplicioTransport,
which executes the pinned simplicio CLI first and uses an already-connected
MCP callback only when the CLI cannot be started.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
import hashlib
import json
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any, Callable

from agent.host_protocol import HOST_PROTOCOL_SCHEMA, host_protocol_metadata
from tools.runtime_handshake import ProtocolRange
from tools.simplicio_transport import SimplicioTransport, TransportReceipt

RUNTIME_BRIDGE_SCHEMA = "simplicio.runtime-bridge/v1"
RUNTIME_COMMAND_SCHEMA = "simplicio.runtime-command/v1"
RUNTIME_RECEIPT_SCHEMA = "simplicio.runtime-bridge-receipt/v1"
RUNTIME_READINESS_SCHEMA = "simplicio.runtime-bridge-readiness/v1"
DEFAULT_RUNTIME_PROTOCOL = ProtocolRange(1, 1)
_FORBIDDEN_COMMAND_CHARS = frozenset(";&|><$" + chr(96) + "\x00\n\r")
_DEFAULT_REQUIRED_SCHEMAS = (
    HOST_PROTOCOL_SCHEMA,
    "simplicio-transport/receipt/v1",
)


class RuntimeBridgeError(ValueError):
    """Raised when a RuntimeBridge request cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class RuntimeBridgeContract:
    """Machine-readable ownership and compatibility boundary."""

    agent_protocol: ProtocolRange
    runtime_protocol: ProtocolRange
    transport: str
    runtime_owner: str = "simplicio-runtime"
    gate_owner: str = "simplicio-runtime"
    required_schemas: tuple[str, ...] = ()
    mutations_require_gate: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.agent_protocol, ProtocolRange) or not isinstance(
            self.runtime_protocol, ProtocolRange
        ):
            raise TypeError("protocols must be ProtocolRange values")
        if not str(self.transport).strip():
            raise ValueError("transport must be non-empty")
        object.__setattr__(self, "transport", str(self.transport).strip())
        schemas = tuple(sorted({str(item).strip() for item in self.required_schemas}))
        if any(not item for item in schemas):
            raise ValueError("required_schemas must contain non-empty values")
        object.__setattr__(self, "required_schemas", schemas)
        if not isinstance(self.mutations_require_gate, bool):
            raise TypeError("mutations_require_gate must be boolean")

    @property
    def compatible(self) -> bool:
        return self.agent_protocol.overlaps(self.runtime_protocol)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_BRIDGE_SCHEMA,
            "agent_protocol": self.agent_protocol.to_dict(),
            "runtime_protocol": self.runtime_protocol.to_dict(),
            "transport": self.transport,
            "runtime_owner": self.runtime_owner,
            "gate_owner": self.gate_owner,
            "required_schemas": list(self.required_schemas),
            "mutations_require_gate": self.mutations_require_gate,
            "compatible": self.compatible,
        }

    def content_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    """JSON-safe command envelope accepted by the bridge."""

    command: str
    arguments: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_COMMAND_SCHEMA,
            "command": self.command,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class RuntimeBridgeReceipt:
    """Stable evidence returned for one Agent -> Runtime invocation."""

    command: str
    arguments: Mapping[str, Any]
    ok: bool
    value: Any = None
    error: Mapping[str, Any] | None = None
    transport: str | None = None
    fallback_reason: str | None = None
    request_id: str | None = None
    deduplicated: bool = False
    schema: str = RUNTIME_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "command": self.command,
            "arguments": dict(self.arguments),
            "ok": self.ok,
            "value": self.value,
            "error": dict(self.error) if self.error is not None else None,
            "transport": self.transport,
            "fallback_reason": self.fallback_reason,
            "request_id": self.request_id,
            "deduplicated": self.deduplicated,
        }


class RuntimeBridge:
    """Importable AgentHost-facing facade over the Runtime CLI and MCP."""

    def __init__(
        self,
        transport: SimplicioTransport | None = None,
        *,
        profile: str = "default",
        contract: RuntimeBridgeContract | None = None,
        cli_bin: str | None = None,
        mcp_call: Callable[[str, dict[str, Any]], Any] | None = None,
        mcp_command: Sequence[str] | None = None,
        idempotency_max_entries: int = 256,
    ) -> None:
        if not isinstance(profile, str) or not profile.strip():
            raise ValueError("profile must be a non-empty string")
        if (
            isinstance(idempotency_max_entries, bool)
            or not isinstance(idempotency_max_entries, int)
            or idempotency_max_entries < 1
        ):
            raise ValueError("idempotency_max_entries must be a positive integer")
        self.profile = profile.strip()
        self.transport = transport or SimplicioTransport(
            cli_bin=cli_bin,
            mcp_call=mcp_call,
            mcp_command=mcp_command,
        )
        self.contract = contract or RuntimeBridgeContract(
            agent_protocol=ProtocolRange(1, 1),
            runtime_protocol=DEFAULT_RUNTIME_PROTOCOL,
            transport="cli+mcp",
            required_schemas=_DEFAULT_REQUIRED_SCHEMAS,
        )
        self._idempotency_max_entries = idempotency_max_entries
        self._seen: OrderedDict[str, tuple[str, RuntimeBridgeReceipt]] = OrderedDict()
        self._lock = Lock()
        self._closed = False

    def __enter__(self) -> "RuntimeBridge":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def host_protocol(self) -> dict[str, Any]:
        """Return the AgentHost discovery envelope used by the daemon."""

        return {
            **host_protocol_metadata(self.profile),
            "bridge_schema": RUNTIME_BRIDGE_SCHEMA,
            "bridge_protocol_version": self.contract.agent_protocol.max,
            "runtime_protocol": self.contract.runtime_protocol.to_dict(),
        }

    metadata = host_protocol

    def readiness(self) -> dict[str, Any]:
        """Return a read-only bridge and transport readiness snapshot."""

        health_fn = getattr(self.transport, "health", None)
        health = dict(health_fn()) if callable(health_fn) else {}
        cli_available = bool(getattr(self.transport, "cli_bin", None))
        if not cli_available:
            resolve_cli = getattr(self.transport, "_resolve_cli", None)
            if callable(resolve_cli):
                try:
                    cli_available = bool(resolve_cli())
                except Exception:
                    cli_available = False
        mcp_available = callable(getattr(self.transport, "mcp_call", None)) or bool(
            getattr(self.transport, "mcp_command", None)
        )
        if self._closed:
            reason = "bridge_closed"
        elif cli_available:
            reason = "cli_ready"
        elif mcp_available:
            reason = "mcp_ready"
        else:
            reason = "runtime_unavailable"
        return {
            "schema": RUNTIME_READINESS_SCHEMA,
            "ready": reason != "bridge_closed" and (cli_available or mcp_available),
            "reason_code": reason,
            "profile": self.profile,
            "host_protocol_schema": HOST_PROTOCOL_SCHEMA,
            "cli_available": cli_available,
            "mcp_available": mcp_available,
            "transport": health,
        }

    def invoke(
        self,
        command: str | Sequence[str],
        arguments: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> RuntimeBridgeReceipt:
        """Invoke one Runtime command through CLI-first/MCP-fallback routing."""

        normalized = self._normalize_command(command)
        args = self._normalize_arguments(arguments)
        request = RuntimeCommand(normalized, args)
        fingerprint = self._fingerprint(request)

        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise RuntimeBridgeError("idempotency_key must be a non-empty string")
            with self._lock:
                cached = self._seen.get(idempotency_key)
                if cached is not None:
                    previous_fingerprint, previous = cached
                    if previous_fingerprint != fingerprint:
                        raise RuntimeBridgeError(
                            "idempotency_key was reused for different Runtime commands"
                        )
                    self._seen.move_to_end(idempotency_key)
                    return replace(previous, deduplicated=True)

        if self._closed:
            return RuntimeBridgeReceipt(
                command=normalized,
                arguments=args,
                ok=False,
                error={
                    "code": "bridge_closed",
                    "message": "RuntimeBridge is closed",
                    "retryable": False,
                },
            )

        if normalized.startswith("simplicio_"):
            tool_name = normalized
            tool_arguments = dict(args)
        else:
            tool_name = "simplicio_exec"
            tool_arguments = {"command": normalized, **args}

        transport_receipt = self.transport.call_tool(tool_name, tool_arguments)
        result = self._receipt(normalized, args, transport_receipt)
        if idempotency_key is not None:
            with self._lock:
                self._seen[idempotency_key] = (fingerprint, result)
                self._seen.move_to_end(idempotency_key)
                while len(self._seen) > self._idempotency_max_entries:
                    self._seen.popitem(last=False)
        return result

    def execute(
        self,
        command: str | Sequence[str],
        arguments: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> RuntimeBridgeReceipt:
        """Alias for callers that prefer CLI terminology."""

        return self.invoke(command, arguments, idempotency_key=idempotency_key)

    call = execute
    run = execute
    invoke_runtime = invoke
    status = readiness

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> RuntimeBridgeReceipt:
        """Invoke an MCP tool by its exact first-party name."""

        return self.invoke(name, arguments, idempotency_key=idempotency_key)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        close_fn = getattr(self.transport, "close", None)
        if callable(close_fn):
            close_fn()

    @staticmethod
    def _normalize_command(command: str | Sequence[str]) -> str:
        if isinstance(command, str):
            normalized = command.strip()
        elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
            if not command or any(not isinstance(item, str) or not item.strip() for item in command):
                raise RuntimeBridgeError("command sequence must contain non-empty strings")
            normalized = " ".join(item.strip() for item in command)
        else:
            raise RuntimeBridgeError("command must be a string or sequence of strings")

        if normalized.startswith("simplicio exec "):
            normalized = normalized[len("simplicio exec ") :].strip()
        if not normalized or any(char in normalized for char in _FORBIDDEN_COMMAND_CHARS):
            raise RuntimeBridgeError(
                "command must be a non-empty shell-free Runtime subcommand"
            )
        return normalized

    @staticmethod
    def _normalize_arguments(arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        if arguments is None:
            return {}
        if not isinstance(arguments, Mapping):
            raise RuntimeBridgeError("arguments must be a mapping")
        result = dict(arguments)
        try:
            json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise RuntimeBridgeError("arguments must be JSON-serializable") from exc
        return result

    @staticmethod
    def _fingerprint(request: RuntimeCommand) -> str:
        payload = json.dumps(
            request.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _receipt(
        command: str,
        arguments: Mapping[str, Any],
        receipt: TransportReceipt,
    ) -> RuntimeBridgeReceipt:
        error = receipt.error.to_dict() if receipt.error is not None else None
        if receipt.ok and receipt.value is None:
            error = {
                "schema": "simplicio-transport/error/v1",
                "code": "missing_observable_value",
                "message": (
                    "Runtime reported success without an observable JSON value"
                ),
                "retryable": False,
            }
        return RuntimeBridgeReceipt(
            command=command,
            arguments=arguments,
            ok=receipt.ok and error is None,
            value=receipt.value,
            error=error,
            transport=receipt.transport,
            fallback_reason=receipt.fallback_reason,
            request_id=receipt.request_id,
        )


__all__ = [
    "DEFAULT_RUNTIME_PROTOCOL",
    "HOST_PROTOCOL_SCHEMA",
    "RUNTIME_BRIDGE_SCHEMA",
    "RUNTIME_COMMAND_SCHEMA",
    "RUNTIME_READINESS_SCHEMA",
    "RUNTIME_RECEIPT_SCHEMA",
    "RuntimeBridge",
    "RuntimeBridgeContract",
    "RuntimeBridgeError",
    "RuntimeBridgeReceipt",
    "RuntimeCommand",
]
