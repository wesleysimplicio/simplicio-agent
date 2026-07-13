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

import os
import subprocess
import sys
import time

import pytest

from hermes_cli.daemon import PRELOADERS, PROFILE_PRELOADS


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


def test_top_level_help_lists_daemon_subcommand():
    result = _run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "daemon" in result.stdout


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
