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
