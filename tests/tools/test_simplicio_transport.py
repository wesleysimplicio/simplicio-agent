"""Contract tests for the CLI-first Simplicio transport boundary."""

from unittest.mock import patch
from threading import Barrier, Thread

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


def test_batch_cli_retries_without_windows_hide_flags_after_launch_error():
    import os
    import subprocess

    if os.name != "nt":
        return
    proc = subprocess.CompletedProcess(
        ["cmd.exe"], 0, stdout='{"decision":"allow"}', stderr=""
    )
    with patch(
        "tools.simplicio_transport.subprocess.run",
        side_effect=[OSError(6, "invalid handle"), proc],
    ) as run:
        receipt = SimplicioTransport(cli_bin="fake.cmd").gate("echo ok")

    assert receipt.ok is True
    assert receipt.transport == "cli"
    assert run.call_count == 2
    assert "creationflags" in run.call_args_list[0].kwargs
    assert "creationflags" not in run.call_args_list[1].kwargs


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


def test_cli_empty_output_is_failure_not_inferred_success():
    import subprocess

    proc = subprocess.CompletedProcess(
        ["simplicio"], 0, stdout="", stderr=""
    )
    with patch("tools.simplicio_transport.subprocess.run", return_value=proc):
        receipt = SimplicioTransport(cli_bin="simplicio").mechanical_edit(
            {"file": "note.txt", "operations": []}
        )

    assert receipt.ok is False
    assert receipt.error.code == "cli_empty_output"


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
        "/bin/simplicio",
        "path",
        "3.5.2",
        "3.5.2",
        True,
        detail="",
        release_repo="wesleysimplicio/simplicio",
        source_repo="wesleysimplicio/simplicio-runtime",
    )
    with patch.object(runtime_manager, "runtime_status", return_value=status):
        health = runtime_manager.runtime_health()
    assert health["healthy"] is True
    assert health["schema"] == "simplicio-runtime/health/v1"
    assert health["reason_code"] == "ready"
    assert health["handshake"] is None
    assert health["transport"] == "path"
    assert health["repo"] == "wesleysimplicio/simplicio"
    assert health["release_repo"] == "wesleysimplicio/simplicio"
    assert health["source_repo"] == "wesleysimplicio/simplicio-runtime"
    assert health["doctor_command"] == "simplicio-agent doctor --fix"

    with patch.object(runtime_manager, "ensure_runtime", return_value=status):
        doctor = runtime_manager.doctor_status()
    assert doctor["healthy"] is True
    assert doctor["schema"] == "simplicio-runtime/doctor/v1"
    assert doctor["reason_code"] == "ready"
    assert doctor["handshake"] is None
    assert doctor["transport"] == "path"
    assert doctor["repo"] == "wesleysimplicio/simplicio"
    assert doctor["release_repo"] == "wesleysimplicio/simplicio"
    assert doctor["source_repo"] == "wesleysimplicio/simplicio-runtime"

    status_dict = status.to_dict()
    assert status_dict["satisfied"] is True
    assert status_dict["reason_code"] == "ready"
    assert status_dict["transport"] == "path"
    assert status_dict["repo"] == "wesleysimplicio/simplicio"


def test_bridge_lifecycle_is_idempotent_and_closed_calls_fail_closed():
    class Stub:
        def __init__(self):
            self.calls = 0

        def gate(self, *args, **kwargs):
            self.calls += 1
            return TransportReceipt.success("gate", {"decision": "allow"})

        def health(self):
            return {"schema": "stub-health", "healthy": True}

    transport = Stub()
    bridge = SimplicioBridge(transport)
    assert bridge.start().state == "ready"
    closed = bridge.close()
    assert closed.state == "closed"
    assert bridge.close() == closed
    assert bridge.gate("echo ok") is None
    assert transport.calls == 0
    assert bridge.health()["healthy"] is False


def test_bridge_idempotency_is_thread_safe_and_bounded():
    class Stub:
        def __init__(self):
            self.calls = 0

        def ledger(self, event):
            self.calls += 1
            return TransportReceipt.success("ledger", True, request_id="req-1")

        def health(self):
            return {"healthy": True}

    transport = Stub()
    bridge = SimplicioBridge(transport, idempotency_max_entries=1)
    barrier = Barrier(2)
    results = []

    def run():
        barrier.wait()
        results.append(bridge.ledger({"id": "same"}, causal_id="same"))

    threads = [Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True, True]
    assert transport.calls == 1
    assert bridge.metrics().last_deduplicated is True

    bridge.ledger({"id": "other"}, causal_id="other")
    bridge.ledger({"id": "third"}, causal_id="third")
    assert len(bridge._seen) == 1


def test_transport_close_returns_typed_failure_without_fallback():
    transport = SimplicioTransport(cli_bin="simplicio", mcp_call=lambda *_: True)
    transport.close()
    receipt = transport.gate("echo ok")
    assert receipt.ok is False
    assert receipt.error.code == "transport_closed"
    assert receipt.fallback_reason is None
    assert transport.health()["state"] == "closed"


def test_gitram_routes_through_cli_with_json_and_parses_value():
    """GitRAM must forward subcommand + args and parse the --json response."""
    payload = (
        '{"acceptable":true,"level":"PairOnly","value_count":4,'
        '"summary":"two-tier verified"}'
    )
    proc = __import__("subprocess").CompletedProcess(
        ["simplicio"], 0, stdout=payload + "\n", stderr=""
    )
    with patch(
        "tools.simplicio_transport.subprocess.run", return_value=proc
    ) as run:
        receipt = SimplicioTransport(cli_bin="simplicio").gitram(
            "consensus", "--values", "a,a,a,b"
        )

    assert receipt.ok is True
    assert receipt.value["acceptable"] is True
    assert receipt.value["value_count"] == 4
    # argv must be: simplicio gitram consensus --values a,a,a,b --json
    argv = run.call_args.args[0]
    assert argv[:2] == ["simplicio", "gitram"]
    assert "--json" in argv
    assert argv[argv.index("--values") + 1] == "a,a,a,b"
