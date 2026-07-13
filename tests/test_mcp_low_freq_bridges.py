"""Tests for mcp_low_freq_bridges — issue #99 low-frequency MCP bridges.

Covers: the domain registry (`LOW_FREQUENCY_DOMAINS`/`list_bridges`), the
CLI-fallback error contract, the three P0 read-only tools (cron/gateway/
hooks status), and MCP registration against a fake FastMCP server.
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Domain registry
# ---------------------------------------------------------------------------

class TestDomainRegistry:
    def test_list_bridges_covers_every_domain(self):
        from mcp_low_freq_bridges import LOW_FREQUENCY_DOMAINS, list_bridges

        bridges = list_bridges()
        assert set(bridges) == set(LOW_FREQUENCY_DOMAINS)

    def test_p0_domains_have_mcp_tool_and_no_fallback_required(self):
        from mcp_low_freq_bridges import list_bridges

        bridges = list_bridges()
        for domain in ("cron", "gateway", "hooks"):
            assert bridges[domain]["status"] == "mcp"
            assert bridges[domain]["mcp_tool"]

    def test_p1_p2_domains_have_no_mcp_tool_but_have_a_fallback_command(self):
        from mcp_low_freq_bridges import list_bridges

        bridges = list_bridges()
        for domain in ("workflow", "issue-factory", "agent", "desktop",
                        "plan", "decide", "sprint", "learn", "doctor",
                        "tokio-runtime", "health", "settings"):
            assert bridges[domain]["status"] == "cli_fallback"
            assert bridges[domain]["mcp_tool"] is None
            assert bridges[domain]["cli_fallback"], f"{domain} has no fallback command"


# ---------------------------------------------------------------------------
# CLI fallback contract
# ---------------------------------------------------------------------------

class TestCliFallbackError:
    def test_known_domain_returns_command(self):
        from mcp_low_freq_bridges import cli_fallback_error

        result = cli_fallback_error("workflow")
        assert result["domain"] == "workflow"
        assert "simplicio workflow" in result["cli_fallback"]
        assert "error" in result

    def test_unknown_domain_lists_known_domains(self):
        from mcp_low_freq_bridges import cli_fallback_error

        result = cli_fallback_error("not-a-real-domain")
        assert "error" in result
        assert "known_domains" in result
        assert "cron" in result["known_domains"]


class TestLowFrequencyCliFallback:
    def test_mcp_domain_reports_its_tool(self):
        from mcp_low_freq_bridges import low_frequency_cli_fallback

        result = low_frequency_cli_fallback("cron")
        assert result["status"] == "mcp"
        assert result["mcp_tool"] == "cron_status"

    def test_cli_fallback_domain_reports_command(self):
        from mcp_low_freq_bridges import low_frequency_cli_fallback

        result = low_frequency_cli_fallback("issue-factory")
        assert result["status"] == "cli_fallback"
        assert "simplicio issue-factory" in result["cli_fallback"]

    def test_case_and_whitespace_insensitive(self):
        from mcp_low_freq_bridges import low_frequency_cli_fallback

        result = low_frequency_cli_fallback("  CRON  ")
        assert result["status"] == "mcp"
        assert result["domain"] == "cron"

    def test_unknown_domain(self):
        from mcp_low_freq_bridges import low_frequency_cli_fallback

        result = low_frequency_cli_fallback("bogus")
        assert "error" in result
        assert "known_domains" in result


# ---------------------------------------------------------------------------
# cron_status — real data path, mocked at the module boundary
# ---------------------------------------------------------------------------

class TestCronStatus:
    def test_builtin_provider_gateway_not_running(self, monkeypatch):
        import cron.jobs as jobs_mod
        import cron.scheduler_provider as sp_mod
        import gateway.status as status_mod

        monkeypatch.setattr(sp_mod, "resolve_cron_scheduler",
                             lambda: SimpleNamespace(name="builtin"))
        monkeypatch.setattr(jobs_mod, "list_jobs", lambda include_disabled=False: [])
        monkeypatch.setattr(status_mod, "get_running_pid", lambda **kw: None)

        from mcp_low_freq_bridges import cron_status

        result = cron_status()
        assert result["provider"] == "builtin"
        assert result["gateway_running"] is False
        assert result["will_fire"] is False
        assert result["active_job_count"] == 0

    def test_builtin_provider_gateway_running_healthy_ticker(self, monkeypatch):
        import cron.jobs as jobs_mod
        import cron.scheduler_provider as sp_mod
        import gateway.status as status_mod

        monkeypatch.setattr(sp_mod, "resolve_cron_scheduler",
                             lambda: SimpleNamespace(name="builtin"))
        monkeypatch.setattr(jobs_mod, "list_jobs", lambda include_disabled=False: [
            {"id": "j1", "name": "daily backup", "next_run_at": "2026-07-14T00:00:00",
             "schedule_display": "daily at midnight"},
        ])
        monkeypatch.setattr(status_mod, "get_running_pid", lambda **kw: 1234)
        monkeypatch.setattr(jobs_mod, "get_ticker_heartbeat_age", lambda: 5.0)
        monkeypatch.setattr(jobs_mod, "get_ticker_success_age", lambda: 5.0)

        from mcp_low_freq_bridges import cron_status

        result = cron_status()
        assert result["gateway_running"] is True
        assert result["gateway_pid"] == 1234
        assert result["will_fire"] is True
        assert result["active_job_count"] == 1
        assert result["active_jobs"][0]["id"] == "j1"

    def test_stalled_ticker_reports_will_not_fire(self, monkeypatch):
        import cron.jobs as jobs_mod
        import cron.scheduler_provider as sp_mod
        import gateway.status as status_mod

        monkeypatch.setattr(sp_mod, "resolve_cron_scheduler",
                             lambda: SimpleNamespace(name="builtin"))
        monkeypatch.setattr(jobs_mod, "list_jobs", lambda include_disabled=False: [])
        monkeypatch.setattr(status_mod, "get_running_pid", lambda **kw: 1234)
        monkeypatch.setattr(jobs_mod, "get_ticker_heartbeat_age", lambda: 99999.0)
        monkeypatch.setattr(jobs_mod, "get_ticker_success_age", lambda: 99999.0)

        from mcp_low_freq_bridges import cron_status

        result = cron_status()
        assert result["will_fire"] is False
        assert result["reason"] == "ticker_stalled"

    def test_external_provider_skips_ticker_heuristics(self, monkeypatch):
        import cron.jobs as jobs_mod
        import cron.scheduler_provider as sp_mod

        monkeypatch.setattr(sp_mod, "resolve_cron_scheduler",
                             lambda: SimpleNamespace(name="chronos"))
        monkeypatch.setattr(jobs_mod, "list_jobs", lambda include_disabled=False: [])

        from mcp_low_freq_bridges import cron_status

        result = cron_status()
        assert result["provider"] == "chronos"
        assert result["will_fire"] == "external_provider"
        assert "gateway_running" not in result

    def test_scheduler_resolution_failure_falls_back_to_builtin(self, monkeypatch):
        import cron.jobs as jobs_mod
        import cron.scheduler_provider as sp_mod
        import gateway.status as status_mod

        def _boom():
            raise RuntimeError("config unreadable")

        monkeypatch.setattr(sp_mod, "resolve_cron_scheduler", _boom)
        monkeypatch.setattr(jobs_mod, "list_jobs", lambda include_disabled=False: [])
        monkeypatch.setattr(status_mod, "get_running_pid", lambda **kw: None)

        from mcp_low_freq_bridges import cron_status

        result = cron_status()
        assert result["provider"] == "builtin"


# ---------------------------------------------------------------------------
# gateway_status
# ---------------------------------------------------------------------------

class TestGatewayStatus:
    def test_running(self, monkeypatch):
        import gateway.status as status_mod

        monkeypatch.setattr(status_mod, "get_running_pid", lambda **kw: 4321)
        from mcp_low_freq_bridges import gateway_status

        result = gateway_status()
        assert result == {"running": True, "pid": 4321}

    def test_not_running(self, monkeypatch):
        import gateway.status as status_mod

        monkeypatch.setattr(status_mod, "get_running_pid", lambda **kw: None)
        from mcp_low_freq_bridges import gateway_status

        result = gateway_status()
        assert result == {"running": False, "pid": None}


# ---------------------------------------------------------------------------
# hooks_status
# ---------------------------------------------------------------------------

class _FakeHookSpec:
    def __init__(self, event, command, matcher=None, timeout=30):
        self.event = event
        self.command = command
        self.matcher = matcher
        self.timeout = timeout


class TestHooksStatus:
    def test_no_hooks_configured(self, monkeypatch):
        from agent import shell_hooks as sh_mod
        import hermes_cli.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "load_config", lambda: {})
        monkeypatch.setattr(sh_mod, "iter_configured_hooks", lambda cfg: [])
        monkeypatch.setattr(sh_mod, "load_allowlist", lambda: {"approvals": []})

        from mcp_low_freq_bridges import hooks_status

        result = hooks_status()
        assert result == {"count": 0, "hooks": []}

    def test_hooks_with_approval_state(self, monkeypatch):
        from agent import shell_hooks as sh_mod
        import hermes_cli.config as cfg_mod

        specs = [
            _FakeHookSpec("PreToolUse", "./notify.sh", matcher="Bash", timeout=15),
            _FakeHookSpec("PostToolUse", "./log.sh"),
        ]
        monkeypatch.setattr(cfg_mod, "load_config", lambda: {"hooks": {}})
        monkeypatch.setattr(sh_mod, "iter_configured_hooks", lambda cfg: specs)
        monkeypatch.setattr(sh_mod, "load_allowlist", lambda: {
            "approvals": [{"event": "PreToolUse", "command": "./notify.sh"}],
        })

        from mcp_low_freq_bridges import hooks_status

        result = hooks_status()
        assert result["count"] == 2
        by_command = {h["command"]: h for h in result["hooks"]}
        assert by_command["./notify.sh"]["approved"] is True
        assert by_command["./notify.sh"]["matcher"] == "Bash"
        assert by_command["./log.sh"]["approved"] is False


# ---------------------------------------------------------------------------
# MCP registration — fake FastMCP, mirrors mcp_serve.py's own test pattern
# ---------------------------------------------------------------------------

class _FakeTool:
    def __init__(self, fn, name=None):
        self.name = name or fn.__name__
        self.description = inspect.getdoc(fn) or ""
        self.fn = fn


class _FakeToolManager:
    def __init__(self):
        self._tools = {}

    def add_tool(self, fn, name=None):
        tool = _FakeTool(fn, name=name)
        self._tools[tool.name] = tool

    def call(self, name, **kwargs):
        return self._tools[name].fn(**kwargs)

    def list_tools(self):
        return list(self._tools.values())


class _FakeFastMCP:
    def __init__(self):
        self._tool_manager = _FakeToolManager()

    def tool(self, name=None, **_kwargs):
        def decorator(fn):
            self._tool_manager.add_tool(fn, name=name)
            return fn

        return decorator


class TestRegisterLowFreqTools:
    def test_registers_four_tools(self):
        from mcp_low_freq_bridges import register_low_freq_tools

        mcp = _FakeFastMCP()
        register_low_freq_tools(mcp)
        names = {t.name for t in mcp._tool_manager.list_tools()}
        assert names == {
            "cron_status", "gateway_status", "hooks_status",
            "low_frequency_cli_fallback",
        }

    def test_tools_have_descriptions(self):
        from mcp_low_freq_bridges import register_low_freq_tools

        mcp = _FakeFastMCP()
        register_low_freq_tools(mcp)
        for tool in mcp._tool_manager.list_tools():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_cron_status_tool_returns_json(self, monkeypatch):
        import cron.jobs as jobs_mod
        import cron.scheduler_provider as sp_mod
        import gateway.status as status_mod

        monkeypatch.setattr(sp_mod, "resolve_cron_scheduler",
                             lambda: SimpleNamespace(name="builtin"))
        monkeypatch.setattr(jobs_mod, "list_jobs", lambda include_disabled=False: [])
        monkeypatch.setattr(status_mod, "get_running_pid", lambda **kw: None)

        from mcp_low_freq_bridges import register_low_freq_tools

        mcp = _FakeFastMCP()
        register_low_freq_tools(mcp)
        raw = mcp._tool_manager.call("cron_status")
        parsed = json.loads(raw)
        assert parsed["provider"] == "builtin"

    def test_low_frequency_cli_fallback_tool_returns_json(self):
        from mcp_low_freq_bridges import register_low_freq_tools

        mcp = _FakeFastMCP()
        register_low_freq_tools(mcp)
        raw = mcp._tool_manager.call("low_frequency_cli_fallback", domain="workflow")
        parsed = json.loads(raw)
        assert parsed["status"] == "cli_fallback"
        assert "simplicio workflow" in parsed["cli_fallback"]


# ---------------------------------------------------------------------------
# Wired into mcp_serve.py's real server
# ---------------------------------------------------------------------------

class TestWiredIntoMcpServe:
    def test_create_mcp_server_includes_low_freq_tools(self, tmp_path, monkeypatch):
        pytest.importorskip("mcp", reason="MCP SDK not installed")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        import mcp_serve

        monkeypatch.setattr(mcp_serve, "_get_sessions_dir", lambda: tmp_path / "sessions")
        server = mcp_serve.create_mcp_server()
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert {"cron_status", "gateway_status", "hooks_status",
                "low_frequency_cli_fallback"} <= names
