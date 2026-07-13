"""Contract tests for the CLI-first Simplicio transport boundary."""

from unittest.mock import patch

import tools.runtime_manager as runtime_manager
from tools.simplicio_bridge import SimplicioBridge
from tools.simplicio_transport import (
    FALLBACK_REASON_CLI_UNAVAILABLE,
    SimplicioTransport,
    TransportReceipt,
)


def test_cli_is_primary_and_receipt_is_uniform():
    proc = __import__("subprocess").CompletedProcess(
        ["simplicio"], 0, stdout='{"decision":"allow"}\n', stderr=""
    )
    with patch("tools.simplicio_transport.subprocess.run", return_value=proc) as run:
        receipt = SimplicioTransport(cli_bin="simplicio").gate("echo ok")

    assert isinstance(receipt, TransportReceipt)
    assert receipt.ok is True
    assert receipt.transport == "cli"
    assert receipt.fallback_reason is None
    assert receipt.to_dict()["schema"] == "simplicio-transport/receipt/v1"
    assert receipt.to_dict()["error"] is None
    assert run.call_args.args[0][:3] == ["simplicio", "gate", "classify"]


def test_mcp_fallback_only_when_cli_cannot_start_and_records_reason():
    ledger_events = []
    with patch(
        "tools.simplicio_transport.subprocess.run",
        side_effect=FileNotFoundError("simplicio missing"),
    ):
        transport = SimplicioTransport(
            cli_bin="simplicio",
            mcp_call=lambda operation, args: {"operation": operation},
            fallback_ledger=ledger_events.append,
        )
        receipt = transport.gate("echo ok")

    assert receipt.ok is True
    assert receipt.transport == "mcp"
    assert receipt.fallback_reason == FALLBACK_REASON_CLI_UNAVAILABLE
    assert ledger_events[0]["reason"] == FALLBACK_REASON_CLI_UNAVAILABLE
    assert transport.health()["fallbacks"] == 1


def test_cli_command_error_does_not_trigger_mcp_fallback():
    proc = __import__("subprocess").CompletedProcess(
        ["simplicio"], 2, stdout="", stderr="policy denied"
    )
    mcp = lambda operation, args: {"unexpected": True}
    with patch("tools.simplicio_transport.subprocess.run", return_value=proc) as run:
        receipt = SimplicioTransport(cli_bin="simplicio", mcp_call=mcp).gate("rm -rf /")

    assert receipt.ok is False
    assert receipt.transport == "cli"
    assert receipt.error.code == "cli_command_failed"
    assert receipt.fallback_reason is None
    assert run.call_count == 1


def test_timeout_is_a_cli_error_not_mcp_fallback():
    import subprocess

    with patch(
        "tools.simplicio_transport.subprocess.run",
        side_effect=subprocess.TimeoutExpired("simplicio", 20),
    ):
        receipt = SimplicioTransport(
            cli_bin="simplicio", mcp_call=lambda operation, args: {"unexpected": True}
        ).gate("echo ok")

    assert receipt.ok is False
    assert receipt.error.code == "cli_timeout"
    assert receipt.fallback_reason is None


def test_bridge_default_uses_cli_first_transport_and_surfaces_health():
    bridge = SimplicioBridge()
    health = bridge.health()
    assert health["transport"]["schema"] == "simplicio-transport/health/v1"
    assert health["transport"]["cli_calls"] == 0


def test_bridge_unwraps_cli_receipt_without_losing_transport_metadata():
    import subprocess

    proc = subprocess.CompletedProcess(
        ["simplicio"], 0, stdout='{"decision":"allow"}', stderr=""
    )
    bridge = SimplicioBridge(SimplicioTransport(cli_bin="simplicio"))
    with patch("tools.simplicio_transport.subprocess.run", return_value=proc):
        assert bridge.gate("echo ok") == {"decision": "allow"}
    assert bridge.metrics().last_transport == "cli"


def test_runtime_health_and_doctor_status_are_json_safe():
    status = runtime_manager.RuntimeStatus(
        "/bin/simplicio", "path", "3.5.2", "3.5.2", True, detail=""
    )
    with patch.object(runtime_manager, "runtime_status", return_value=status):
        health = runtime_manager.runtime_health()
    assert health["healthy"] is True
    assert health["schema"] == "simplicio-runtime/health/v1"
    assert health["doctor_command"] == "simplicio-agent doctor --fix"

    with patch.object(runtime_manager, "ensure_runtime", return_value=status):
        doctor = runtime_manager.doctor_status()
    assert doctor["healthy"] is True
    assert doctor["schema"] == "simplicio-runtime/doctor/v1"
