from unittest.mock import patch

import pytest

from agent.runtime_bridge import (
    HOST_PROTOCOL_SCHEMA,
    RuntimeBridge,
    RuntimeBridgeContract,
    RuntimeBridgeError,
)
from tools.runtime_handshake import ProtocolRange
from tools.simplicio_transport import SimplicioTransport


def test_runtime_bridge_contract_keeps_gate_ownership_explicit():
    bridge = RuntimeBridgeContract(
        agent_protocol=ProtocolRange(1, 2),
        runtime_protocol=ProtocolRange(2, 2),
        transport="local-mcp",
        required_schemas=("simplicio.run-event/v1",),
    )
    assert bridge.compatible
    assert bridge.to_dict()["gate_owner"] == "simplicio-runtime"
    assert bridge.to_dict()["mutations_require_gate"] is True
    assert len(bridge.content_hash()) == 64


def test_runtime_bridge_exposes_agenthost_discovery_metadata():
    bridge = RuntimeBridge(cli_bin="/definitely/missing/simplicio", profile="desktop")
    metadata = bridge.host_protocol()
    assert metadata["protocol_schema"] == HOST_PROTOCOL_SCHEMA
    assert metadata["bridge_schema"] == "simplicio.runtime-bridge/v1"
    assert "turn.start" in metadata["capabilities"]


def test_runtime_bridge_routes_cli_shaped_commands_to_runtime_exec():
    calls = []

    class FakeTransport:
        def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return type(
                "Receipt",
                (),
                {
                    "ok": True,
                    "value": {"status": "ok"},
                    "error": None,
                    "transport": "cli",
                    "fallback_reason": None,
                    "request_id": "request-1",
                },
            )()

    bridge = RuntimeBridge(transport=FakeTransport())
    receipt = bridge.invoke("doctor", {"repo": "."})
    assert receipt.ok
    assert receipt.value == {"status": "ok"}
    assert calls == [("simplicio_exec", {"command": "doctor", "repo": "."})]


def test_runtime_bridge_rejects_success_without_observable_value():
    class EmptySuccessTransport:
        def call_tool(self, name, arguments):
            return type(
                "Receipt",
                (),
                {
                    "ok": True,
                    "value": None,
                    "error": None,
                    "transport": "cli",
                    "fallback_reason": None,
                    "request_id": "request-empty-success",
                },
            )()

    receipt = RuntimeBridge(transport=EmptySuccessTransport()).invoke("doctor")

    assert not receipt.ok
    assert receipt.value is None
    assert receipt.error == {
        "schema": "simplicio-transport/error/v1",
        "code": "missing_observable_value",
        "message": "Runtime reported success without an observable JSON value",
        "retryable": False,
    }


def test_runtime_bridge_preserves_observable_success_payload():
    class ValueTransport:
        def call_tool(self, name, arguments):
            return type(
                "Receipt",
                (),
                {
                    "ok": True,
                    "value": {"healthy": True},
                    "error": None,
                    "transport": "cli",
                    "fallback_reason": None,
                    "request_id": "request-value-success",
                },
            )()

    receipt = RuntimeBridge(transport=ValueTransport()).invoke("doctor")

    assert receipt.ok
    assert receipt.value == {"healthy": True}
    assert receipt.error is None


def test_runtime_bridge_uses_mcp_channel_when_cli_is_unavailable():
    calls = []

    def mcp_call(operation, arguments):
        calls.append((operation, arguments))
        return {"status": "ok", "source": "mcp"}

    bridge = RuntimeBridge(
        transport=SimplicioTransport(
            cli_bin="/definitely/missing/simplicio",
            mcp_call=mcp_call,
        )
    )
    receipt = bridge.invoke("doctor", {"repo": "."})
    assert receipt.ok
    assert receipt.transport == "mcp"
    assert receipt.value == {"status": "ok", "source": "mcp"}
    assert calls == [
        (
            "runtime_tool",
            {"name": "simplicio_exec", "arguments": {"command": "doctor", "repo": "."}},
        )
    ]


def test_runtime_bridge_deduplicates_idempotent_requests():
    calls = []

    class FakeTransport:
        def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return type(
                "Receipt",
                (),
                {
                    "ok": True,
                    "value": {"status": "ok"},
                    "error": None,
                    "transport": "mcp",
                    "fallback_reason": "cli_unavailable",
                    "request_id": "request-1",
                },
            )()

    bridge = RuntimeBridge(transport=FakeTransport())
    first = bridge.invoke("status", idempotency_key="same-request")
    second = bridge.invoke("status", idempotency_key="same-request")
    assert first.ok and second.ok
    assert second.deduplicated
    assert len(calls) == 1


def test_runtime_bridge_rejects_shell_syntax_and_non_json_arguments():
    bridge = RuntimeBridge(transport=object())
    with pytest.raises(RuntimeBridgeError):
        bridge.invoke("doctor; rm -rf /")
    with pytest.raises(RuntimeBridgeError):
        bridge.invoke("doctor", {"bad": object()})


def test_runtime_transport_maps_generic_exec_to_cli():
    proc = type("Proc", (), {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""})()
    with patch("tools.simplicio_transport.subprocess.run", return_value=proc) as run:
        receipt = SimplicioTransport(cli_bin="simplicio").call_tool(
            "simplicio_exec",
            {"command": "doctor", "repo": "."},
        )
    assert receipt.ok
    assert run.call_args.args[0][:3] == ["simplicio", "exec", "doctor"]
    assert "--repo" in run.call_args.args[0]
