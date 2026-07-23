"""Tests for the ``hermes_cli.daemon`` warm daemon.

Covers two things:

1. Each real preloader returns genuine data pulled from this repo's actual
   systems (toolsets, skills/ tree, agent/models_dev.py provider map,
   hermes_cli/mcp_catalog.py, hermes_state.SessionDB) — not the old
   hardcoded/stub values the daemon shipped with upstream (e.g.
   ``_preload_provider_metadata`` used to unconditionally return
   ``["deepseek", "openai", "anthropic"]``; ``_preload_mcp_fingerprints``
   used to unconditionally return ``{}``).
2. The ``simplicio-agent daemon`` CLI subcommand is registered and reachable, and a
   real start/status/stop round trip over the UNIX socket works.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from hermes_cli.daemon import PRELOADERS, PROFILE_PRELOADS, _client_request


# ---------------------------------------------------------------------------
# Preloaders return genuine data, not stub values
# ---------------------------------------------------------------------------


def test_preloaders_registered_for_all_profiles():
    assert set(PRELOADERS) == {
        "tool_registry",
        "skill_index",
        "provider_metadata",
        "mcp_fingerprints",
        "session_summaries",
    }
    assert PROFILE_PRELOADS["desktop"] == tuple(PRELOADERS)
    assert PROFILE_PRELOADS["car"] == ("tool_registry", "skill_index", "provider_metadata")


def test_preload_tool_registry_returns_real_toolsets():
    result = PRELOADERS["tool_registry"]()
    assert result["ok"] is True
    # Real toolsets.py has dozens of registered toolsets; a stub/fake
    # implementation would not know this count without importing the module.
    assert result["toolset_count"] > 0
    assert "toolsets" in result
    assert isinstance(result["toolsets"], list)
    assert result["module"] == "toolsets"


def test_preload_skill_index_returns_real_skill_count():
    result = PRELOADERS["skill_index"]()
    assert result["ok"] is True
    # This repo ships skills/ with nested category dirs — a naive
    # top-level glob (the upstream stub's approach) undercounts them.
    assert result["count"] > 0
    assert isinstance(result["skills"], list)
    assert len(result["skills"]) == result["count"]


def test_preload_provider_metadata_is_not_the_old_hardcoded_stub():
    result = PRELOADERS["provider_metadata"]()
    assert result["ok"] is True
    providers = result["providers"]
    # The upstream stub always returned exactly this fixed list regardless
    # of environment. The real list (from agent/models_dev.py) is larger
    # and provider-map-derived.
    assert providers != ["deepseek", "openai", "anthropic"]
    assert len(providers) > 3
    assert "anthropic" in providers
    assert "openai" in providers
    assert result["count"] == len(providers)


def test_preload_mcp_fingerprints_is_wired_to_real_catalog():
    result = PRELOADERS["mcp_fingerprints"]()
    assert result["ok"] is True
    # Genuinely wired (not the upstream stub's unconditional {}): the shape
    # reflects hermes_cli.mcp_catalog.installed_servers()'s real return type,
    # and count is derived rather than a literal 0 baked into the function.
    assert isinstance(result["fingerprints"], dict)
    assert result["count"] == len(result["fingerprints"])


def test_preload_session_summaries_reads_real_sessiondb():
    result = PRELOADERS["session_summaries"]()
    assert result["ok"] is True
    assert isinstance(result["summaries"], list)
    assert result["count"] == len(result["summaries"])
    for summary in result["summaries"]:
        assert "id" in summary
        assert "last_active" in summary


def test_preloaders_never_raise_and_degrade_gracefully(monkeypatch):
    """Simulate an unavailable subsystem: preloader must return ok=False, not raise."""
    from hermes_cli import daemon as daemon_mod

    monkeypatch.setattr(
        daemon_mod, "_preload_session_summaries",
        lambda: {"ok": False, "error": "forced failure for test"},
    )
    result = daemon_mod._preload_session_summaries()
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# CLI subcommand registration + reachability
# ---------------------------------------------------------------------------


def _run_cli(*argv, timeout=15):
    return subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_daemon_help_is_registered():
    result = _run_cli("daemon", "--help")
    assert result.returncode == 0, result.stderr
    assert "start" in result.stdout
    assert "stop" in result.stdout
    assert "status" in result.stdout
    assert "invalidate" in result.stdout


def test_daemon_start_help_uses_warm_profile_flag_not_global_profile():
    """Regression guard: ``--profile`` collides with the global Hermes
    environment-profile pre-parser in hermes_cli/main.py
    (``_apply_profile_override``), which strips ``--profile``/``-p`` from
    argv before argparse ever sees it. The daemon's warm-cache selector
    must use a different flag name (``--warm-profile``) or it gets silently
    swallowed by that unrelated global mechanism.
    """
    result = _run_cli("daemon", "start", "--help")
    assert result.returncode == 0, result.stderr
    assert "--warm-profile" in result.stdout


def test_daemon_status_help_reachable():
    result = _run_cli("daemon", "status", "--help")
    assert result.returncode == 0, result.stderr


def test_windows_loopback_sidecars_are_private_and_reject_nonlocal_endpoints(tmp_path):
    """The Windows fallback may discover only an authenticated loopback host."""
    from hermes_cli import daemon as daemon_mod

    sock_path = tmp_path / "daemon.sock"
    daemon_mod._tcp_endpoint_path(sock_path).write_text("127.0.0.1:43123\n")
    daemon_mod._tcp_token_path(sock_path).write_text("a" * 43 + "\n")
    assert daemon_mod._read_tcp_endpoint(sock_path) == ("127.0.0.1", 43123)
    assert daemon_mod._read_tcp_token(sock_path) == "a" * 43

    daemon_mod._tcp_endpoint_path(sock_path).write_text("192.0.2.1:43123\n")
    assert daemon_mod._read_tcp_endpoint(sock_path) is None
    daemon_mod._tcp_token_path(sock_path).write_text("short\n")
    assert daemon_mod._read_tcp_token(sock_path) is None


def test_daemon_host_status_round_trip_uses_authenticated_local_transport(monkeypatch, tmp_path):
    """A Windows AF_UNIX-less host is discoverable only through its tokenized loopback sidecars."""
    from hermes_cli import daemon as daemon_mod

    monkeypatch.setitem(daemon_mod.PROFILE_PRELOADS, "car", ())
    sock_path = tmp_path / "daemon.sock"
    result: list[int] = []
    worker = threading.Thread(
        target=lambda: result.append(daemon_mod._serve(sock_path, "car", idle_ttl_s=20)),
        daemon=True,
    )
    worker.start()
    endpoint = sock_path if daemon_mod._local_transport_available() else daemon_mod._tcp_endpoint_path(sock_path)
    deadline = time.time() + 10
    while time.time() < deadline and not endpoint.exists():
        time.sleep(0.05)
    assert endpoint.exists(), "daemon did not publish its local endpoint"

    status = daemon_mod._client_request(sock_path, {"op": "host.status"})
    assert status["ok"] is True
    assert status["host"]["ready"] is True
    assert status["host_instance_id"] == status["host"]["host_instance_id"]
    assert status["protocol_schema"] == "simplicio.agent-host/v1"

    stopped = daemon_mod._client_request(sock_path, {"op": "shutdown"})
    assert stopped["ok"] is True
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert result == [0]


def test_daemon_publishes_cancel_and_reconcile_capabilities(monkeypatch):
    from hermes_cli import daemon as daemon_mod

    monkeypatch.setitem(daemon_mod.PROFILE_PRELOADS, "car", ())
    fd, raw_path = tempfile.mkstemp(prefix="agent-e2e-", suffix=".sock", dir="/tmp")
    os.close(fd)
    sock_path = Path(raw_path)
    sock_path.unlink()
    result: list[int] = []
    worker = threading.Thread(
        target=lambda: result.append(daemon_mod._serve(sock_path, "car", idle_ttl_s=20)),
        daemon=True,
    )
    worker.start()
    deadline = time.time() + 10
    while time.time() < deadline and not sock_path.exists():
        time.sleep(0.05)
    status = daemon_mod._client_request(sock_path, {"op": "host.status"})
    assert status["protocol_schema"] == "simplicio.agent-host/v1"
    assert {"turn.cancel", "turn.reconcile"}.issubset(status["capabilities"])
    identity = status["host_instance_id"]
    cancel = daemon_mod._client_request(
        sock_path,
        {"op": "turn.cancel", "turn_id": "missing", "host_instance_id": identity},
    )
    reconcile = daemon_mod._client_request(
        sock_path,
        {"op": "turn.reconcile", "turn_id": "missing", "host_instance_id": identity},
    )
    assert cancel["status"] == "not_found"
    assert reconcile["status"] == "not_found"
    daemon_mod._client_request(sock_path, {"op": "shutdown"})
    worker.join(timeout=10)
    assert result == [0]


def test_top_level_help_lists_daemon_subcommand():
    result = _run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "daemon" in result.stdout


def test_workspace_request_handler_is_effect_free_and_fail_closed():
    from agent.host_protocol import WorkspaceAdvisoryStore
    from hermes_cli import daemon as daemon_mod

    handler = getattr(daemon_mod, "_handle_workspace_request", None)
    assert callable(handler)
    store = WorkspaceAdvisoryStore(max_workspaces=2, max_events_per_workspace=4)

    observed = handler(
        {
            "op": "workspace.observe",
            "workspace_id": "client-workspace-1",
            "revision": 1,
            "snapshot": {
                "changed_files": 1,
                "diagnostic_errors": 0,
                "diagnostic_warnings": 0,
                "test_status": "not_run",
            },
        },
        store,
    )
    assert observed["ok"] is True
    assert observed["observation"]["effect"] == "none"

    replayed = handler(
        {
            "op": "workspace.advisory",
            "workspace_id": "client-workspace-1",
            "cursor": 0,
        },
        store,
    )
    assert replayed["ok"] is True
    assert [
        event["kind"] for event in replayed["workspace_advisories"]["events"]
    ] == ["finding", "suggestion"]

    rejected = handler(
        {
            "op": "workspace.observe",
            "workspace_id": "client-workspace-1",
            "revision": 2,
            "snapshot": {
                "changed_files": 0,
                "diagnostic_errors": 0,
                "diagnostic_warnings": 0,
                "test_status": "unknown",
            },
            "prompt": "do not retain this",
        },
        store,
    )
    assert rejected["ok"] is False
    assert "prompt" not in rejected["error"]


def test_daemon_replay_handlers_bind_both_streams_to_one_host_incarnation():
    from agent.host_protocol import HostAdvisoryBuffer, WorkspaceAdvisoryStore
    from hermes_cli import daemon as daemon_mod

    host_instance_id = "process-incarnation-000001"
    host_advisories = HostAdvisoryBuffer(host_instance_id=host_instance_id)
    host_advisories.publish("host.ready")
    workspace_advisories = WorkspaceAdvisoryStore(host_instance_id=host_instance_id)

    host_reply = daemon_mod._handle_host_advisory_request(
        {"op": "host.advisories", "cursor": 0, "host_instance_id": host_instance_id},
        host_advisories,
        host_instance_id=host_instance_id,
    )
    assert host_reply["ok"] is True
    assert host_reply["advisories"]["schema"] == "simplicio.agent-advisory/v1"
    assert host_reply["advisories"]["host_instance_id"] == host_instance_id
    assert host_reply["advisories"]["next_cursor"] == 1
    assert [event["kind"] for event in host_reply["advisories"]["events"]] == [
        "host.ready"
    ]

    observed = daemon_mod._handle_workspace_request(
        {
            "op": "workspace.observe",
            "workspace_id": "workspace-a",
            "revision": 1,
            "snapshot": {
                "changed_files": 0,
                "diagnostic_errors": 0,
                "diagnostic_warnings": 0,
                "test_status": "passing",
            },
            "host_instance_id": host_instance_id,
        },
        workspace_advisories,
        host_instance_id=host_instance_id,
    )
    assert observed["ok"] is True
    assert observed["observation"]["host_instance_id"] == host_instance_id

    workspace_reply = daemon_mod._handle_workspace_request(
        {
            "op": "workspace.advisory",
            "workspace_id": "workspace-a",
            "cursor": 0,
            "host_instance_id": host_instance_id,
        },
        workspace_advisories,
        host_instance_id=host_instance_id,
    )
    assert workspace_reply["ok"] is True
    assert workspace_reply["workspace_advisories"]["host_instance_id"] == host_instance_id


@pytest.mark.parametrize("op", ["host.advisories", "workspace.advisory"])
@pytest.mark.parametrize("stale", ["process-incarnation-000002", None])
def test_daemon_replay_handlers_reject_a_stale_host_incarnation(op, stale):
    from agent.host_protocol import HostAdvisoryBuffer, WorkspaceAdvisoryStore
    from hermes_cli import daemon as daemon_mod

    current = "process-incarnation-000001"
    if op == "host.advisories":
        response = daemon_mod._handle_host_advisory_request(
            {"op": op, "cursor": 0, "host_instance_id": stale},
            HostAdvisoryBuffer(host_instance_id=current),
            host_instance_id=current,
        )
    else:
        response = daemon_mod._handle_workspace_request(
            {
                "op": op,
                "workspace_id": "workspace-a",
                "cursor": 0,
                "host_instance_id": stale,
            },
            WorkspaceAdvisoryStore(host_instance_id=current),
            host_instance_id=current,
        )

    assert response["ok"] is False
    if stale is None:
        assert "opaque 16-64" in response["error"]
    else:
        assert "does not match" in response["error"]
    if stale is not None:
        assert stale not in response["error"]


def test_daemon_rejects_non_object_json_requests_without_echoing_content():
    from hermes_cli import daemon as daemon_mod

    validator = getattr(daemon_mod, "_request_object", None)
    assert callable(validator)
    request = {"op": "workspace.advisory", "workspace_id": "workspace-a"}
    assert validator(request) is request
    with pytest.raises(ValueError, match="request must be an object") as rejected:
        validator(["private-content"])
    assert "private-content" not in str(rejected.value)


@pytest.mark.skipif(sys.platform == "win32", reason="AF_UNIX sockets used by the daemon")
def test_daemon_start_status_stop_round_trip():
    """Real start/status/invalidate/stop round trip over a UNIX socket.

    Uses a short path under /tmp (not the pytest tmp_path fixture) because
    AF_UNIX socket paths are capped at ~104 chars on macOS/BSD and deep
    pytest tmp dirs routinely exceed that.
    """
    sock_path = f"/tmp/hermes_daemon_test_{os.getpid()}_{int(time.time())}.sock"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "hermes_cli.main", "daemon", "start",
            "--warm-profile", "car", "--socket", sock_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not os.path.exists(sock_path):
            time.sleep(0.2)
        assert os.path.exists(sock_path), "daemon did not create its socket in time"

        status = _run_cli("daemon", "status", "--socket", sock_path)
        assert status.returncode == 0, status.stderr
        assert '"ok": true' in status.stdout
        assert '"profile": "car"' in status.stdout
        # car profile only preloads these three caches
        assert "tool_registry" in status.stdout
        assert "skill_index" in status.stdout
        assert "provider_metadata" in status.stdout

        status_payload = json.loads(status.stdout)
        assert status_payload["protocol_schema"] == "simplicio.agent-host/v1"
        assert status_payload["protocol_version"] == 1
        assert status_payload["agent_protocol"] == "agent/v1"
        host_instance_id = status_payload["host_instance_id"]
        assert 16 <= len(host_instance_id) <= 64
        assert {
            "host.status",
            "host.advisories",
            "turn.start",
        }.issubset(status_payload["capabilities"])

        ping_payload = _client_request(sock_path, {"op": "ping"})
        assert ping_payload["protocol_version"] == 1
        assert ping_payload["agent_protocol"] == "agent/v1"
        assert ping_payload["host_instance_id"] == host_instance_id

        host_payload = _client_request(sock_path, {"op": "host.status"})
        assert host_payload["protocol_version"] == 1
        assert host_payload["host"]["ready"] is True
        assert host_payload["host"]["host_instance_id"] == host_instance_id

        advisory_payload = _client_request(
            sock_path,
            {
                "op": "host.advisories",
                "cursor": 0,
                "host_instance_id": host_instance_id,
            },
        )
        assert advisory_payload["protocol_version"] == 1
        assert advisory_payload["advisories"]["schema"] == "simplicio.agent-advisory/v1"
        assert advisory_payload["advisories"]["events"][0]["kind"] == "host.ready"
        assert advisory_payload["advisories"]["host_instance_id"] == host_instance_id
        cursor = advisory_payload["advisories"]["next_cursor"]
        replay = _client_request(
            sock_path,
            {
                "op": "host.advisories",
                "cursor": cursor,
                "host_instance_id": host_instance_id,
            },
        )
        assert replay["advisories"]["events"] == []
        assert replay["advisories"]["next_cursor"] == cursor

        observation = _client_request(
            sock_path,
            {
                "op": "workspace.observe",
                "workspace_id": "client-workspace-1",
                "revision": 1,
                "snapshot": {
                    "changed_files": 3,
                    "diagnostic_errors": 1,
                    "diagnostic_warnings": 0,
                    "test_status": "not_run",
                },
                "host_instance_id": host_instance_id,
            },
        )
        assert observation["ok"] is True
        assert observation["observation"]["effect"] == "none"
        assert observation["observation"]["published_count"] == 3
        assert observation["workspace_observation_schema"] == (
            "simplicio.workspace-observation/v1"
        )
        assert observation["observation"]["host_instance_id"] == host_instance_id

        workspace_replay = _client_request(
            sock_path,
            {
                "op": "workspace.advisory",
                "workspace_id": "client-workspace-1",
                "cursor": 0,
                "host_instance_id": host_instance_id,
            },
        )
        assert workspace_replay["ok"] is True
        assert workspace_replay["workspace_advisories"]["schema"] == (
            "simplicio.workspace-advisory/v1"
        )
        assert [
            event["kind"]
            for event in workspace_replay["workspace_advisories"]["events"]
        ] == ["finding", "risk", "suggestion"]
        assert all(
            event["effect"] == "none"
            for event in workspace_replay["workspace_advisories"]["events"]
        )
        assert (
            workspace_replay["workspace_advisories"]["host_instance_id"]
            == host_instance_id
        )

        future_workspace_cursor = _client_request(
            sock_path,
            {
                "op": "workspace.advisory",
                "workspace_id": "client-workspace-1",
                "cursor": 4,
                "host_instance_id": host_instance_id,
            },
        )
        assert future_workspace_cursor["ok"] is False
        assert "exceeds" in future_workspace_cursor["error"]

        stale_instance = "different-host-instance-00001"
        stale_host_cursor = _client_request(
            sock_path,
            {
                "op": "host.advisories",
                "cursor": cursor,
                "host_instance_id": stale_instance,
            },
        )
        assert stale_host_cursor["ok"] is False
        assert "does not match" in stale_host_cursor["error"]
        assert stale_instance not in stale_host_cursor["error"]

        invalidate = _run_cli(
            "daemon", "invalidate", "provider_metadata", "--socket", sock_path
        )
        assert invalidate.returncode == 0, invalidate.stderr
        assert '"ok": true' in invalidate.stdout

        stop = _run_cli("daemon", "stop", "--socket", sock_path)
        assert stop.returncode == 0, stop.stderr
        assert '"ok": true' in stop.stdout
    finally:
        proc.wait(timeout=10)
        for path in (sock_path, sock_path.replace(".sock", ".pid")):
            try:
                os.unlink(path)
            except OSError:
                pass


@pytest.mark.skipif(sys.platform == "win32", reason="AF_UNIX sockets used by the daemon")
def test_daemon_status_reports_idle_ttl_fields():
    """AC (#110): the daemon self-reports its idle-TTL state, which
    ``simplicio-agent doctor`` surfaces (``hermes_cli/doctor.py::_check_warm_daemon``).
    """
    sock_path = f"/tmp/hermes_daemon_ttl_status_{os.getpid()}_{int(time.time())}.sock"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "hermes_cli.main", "daemon", "start",
            "--warm-profile", "car", "--socket", sock_path, "--idle-ttl-s", "60",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not os.path.exists(sock_path):
            time.sleep(0.2)
        assert os.path.exists(sock_path), "daemon did not create its socket in time"

        status = _run_cli("daemon", "status", "--socket", sock_path)
        assert status.returncode == 0, status.stderr
        assert '"idle_ttl_s": 60.0' in status.stdout
        assert '"idle_s"' in status.stdout
    finally:
        _run_cli("daemon", "stop", "--socket", sock_path)
        proc.wait(timeout=10)
        for path in (sock_path, sock_path.replace(".sock", ".pid")):
            try:
                os.unlink(path)
            except OSError:
                pass


@pytest.mark.skipif(sys.platform == "win32", reason="AF_UNIX sockets used by the daemon")
def test_daemon_shuts_itself_down_after_idle_ttl():
    """AC (#110): daemon self-terminates once the idle TTL elapses with no
    connections — a short TTL is injected via ``--idle-ttl-s`` (equivalent to
    the env override ``SIMPLICIO_AGENT_DAEMON_IDLE_TTL_S`` the daemon also
    honors) so the test doesn't wait 30 real minutes.
    """
    sock_path = f"/tmp/hermes_daemon_idle_shutdown_{os.getpid()}_{int(time.time())}.sock"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "hermes_cli.main", "daemon", "start",
            "--warm-profile", "car", "--socket", sock_path, "--idle-ttl-s", "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not os.path.exists(sock_path):
            time.sleep(0.2)
        assert os.path.exists(sock_path), "daemon did not create its socket in time"

        # Do NOT talk to the socket again — any request would reset
        # last-activity and defeat the point of this test.
        exit_code = proc.wait(timeout=15)
        assert exit_code == 0, proc.stdout.read() if proc.stdout else ""
        assert not os.path.exists(sock_path), "daemon left its socket behind after idle shutdown"
    finally:
        for path in (sock_path, sock_path.replace(".sock", ".pid")):
            try:
                os.unlink(path)
            except OSError:
                pass


def test_no_daemon_opt_out_env_flag(monkeypatch):
    from hermes_cli import daemon as daemon_mod

    monkeypatch.delenv("SIMPLICIO_AGENT_NO_DAEMON", raising=False)
    assert daemon_mod._no_daemon_opt_out() is False

    monkeypatch.setenv("SIMPLICIO_AGENT_NO_DAEMON", "1")
    assert daemon_mod._no_daemon_opt_out() is True

    monkeypatch.setenv("SIMPLICIO_AGENT_NO_DAEMON", "0")
    assert daemon_mod._no_daemon_opt_out() is False


def test_maybe_autostart_respects_no_daemon_opt_out(monkeypatch, tmp_path):
    """AC (#110): ``SIMPLICIO_AGENT_NO_DAEMON=1`` → no background process is
    ever spawned, asserted directly against ``subprocess.Popen`` never being
    called (stronger than a process-table scan: it proves this code path
    can't spawn anything, not just that nothing happened to be running).
    """
    from hermes_cli import daemon as daemon_mod

    monkeypatch.setenv("SIMPLICIO_AGENT_NO_DAEMON", "1")
    calls = []
    monkeypatch.setattr(daemon_mod.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))

    sock_path = tmp_path / "daemon.sock"
    spawned = daemon_mod.maybe_autostart(sock_path=sock_path)

    assert spawned is False
    assert calls == []


def test_maybe_autostart_skips_when_already_running(monkeypatch, tmp_path):
    from hermes_cli import daemon as daemon_mod

    monkeypatch.delenv("SIMPLICIO_AGENT_NO_DAEMON", raising=False)
    monkeypatch.setattr(daemon_mod, "is_daemon_running", lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(daemon_mod.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))

    sock_path = tmp_path / "daemon.sock"
    spawned = daemon_mod.maybe_autostart(sock_path=sock_path)

    assert spawned is False
    assert calls == []


def test_maybe_autostart_spawns_detached_process_when_cold(monkeypatch, tmp_path):
    """When no daemon is running and the opt-out is unset, a real background
    process is spawned (detached: ``start_new_session=True`` on POSIX) with
    the socket path and profile threaded through.
    """
    from hermes_cli import daemon as daemon_mod

    monkeypatch.delenv("SIMPLICIO_AGENT_NO_DAEMON", raising=False)
    monkeypatch.setattr(daemon_mod, "is_daemon_running", lambda *a, **k: False)
    calls = []

    class _FakeProc:
        pid = 12345

    def _fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return _FakeProc()

    monkeypatch.setattr(daemon_mod.subprocess, "Popen", _fake_popen)

    sock_path = tmp_path / "profile-a" / "daemon.sock"
    spawned = daemon_mod.maybe_autostart(sock_path=sock_path, profile="car")

    assert spawned is True
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert "hermes_cli.daemon" in argv and "start" in argv
    assert "--warm-profile" in argv and "car" in argv
    assert "--socket" in argv and str(sock_path) in argv
    if sys.platform != "win32":
        assert kwargs.get("start_new_session") is True
    # The socket's parent dir must exist so the real daemon can bind it.
    assert sock_path.parent.exists()


def test_daemon_status_without_running_daemon_falls_back_cold():
    """When no daemon is listening, status must report a cold fallback
    rather than hanging or raising. Note: hermes_cli/main.py's top-level
    dispatch (``args.func(args)``) does not propagate handler return codes
    to the process exit status for any subcommand (same for cmd_cron,
    cmd_gateway, etc.), so this asserts on the JSON payload, not returncode.
    """
    sock_path = f"/tmp/hermes_daemon_missing_{os.getpid()}.sock"
    result = _run_cli("daemon", "status", "--socket", sock_path)
    assert result.returncode == 0
    assert "daemon not running" in result.stdout
    assert "cold" in result.stdout
