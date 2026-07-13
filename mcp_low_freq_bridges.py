"""MCP Low-Frequency Bridges — cron, gateway, hooks, and CLI-fallback contract.

Phase 2 of issue #99. See `docs/mcp-low-frequency-bridges.md` for the full
classification of the low-frequency command tail (cron, gateway, workflow,
issue-factory, agent, desktop, plan/decide/sprint/learn,
doctor/hooks/tokio-runtime/health/settings) and which domains graduate to a
real MCP tool (P0) versus stay an explicit, documented CLI fallback (P1/P2).

Design constraints, on purpose:
  * This module is imported by `mcp_serve.py` (`register_low_freq_tools`)
    but is otherwise fully independent of it, so it can be unit-tested
    without booting a FastMCP server or the messaging bridge.
  * Every P0 tool here wraps a *read-only* data path that already exists
    natively in this Python codebase (`cron.jobs`, `gateway.status`,
    `agent.shell_hooks`) — no new side-effecting surface, no shelling out
    to the separate `simplicio` Rust runtime binary.
  * Anything not promoted to a tool gets `cli_fallback_error`, a single
    consistent error contract (never a bare exception or a silent no-op)
    pointing the caller at the exact CLI command to run instead.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Domain registry — single source of truth for "is this domain MCP or CLI
# fallback", mirroring the table in docs/mcp-low-frequency-bridges.md.
# Keep this dict and that doc's table in sync when a domain graduates.
# ---------------------------------------------------------------------------

#: domain -> MCP tool name, or None when the domain is CLI-fallback only.
LOW_FREQUENCY_DOMAINS: Dict[str, Optional[str]] = {
    "cron": "cron_status",
    "gateway": "gateway_status",
    "hooks": "hooks_status",
    "workflow": None,
    "issue-factory": None,
    "agent": None,
    "desktop": None,
    "plan": None,
    "decide": None,
    "sprint": None,
    "learn": None,
    "doctor": None,
    "tokio-runtime": None,
    "health": None,
    "settings": None,
}

#: domain -> the CLI command an agent should fall back to. Kept next to
#: LOW_FREQUENCY_DOMAINS so the fallback message always names a real command.
_CLI_FALLBACK_COMMANDS: Dict[str, str] = {
    "cron": "simplicio-agent cron add|tick|run|pause|resume|remove",
    "gateway": "simplicio-agent gateway setup|start|stop|restart",
    "hooks": "simplicio-agent hooks test|revoke",
    "workflow": "simplicio workflow run|resume|retry|watch --repo <path> [--json]",
    "issue-factory": "simplicio issue-factory run|claim|pr-handoff|comment --repo <path> [--json]",
    "agent": "simplicio agents delegate <goal>|children|pause|resume|interrupt [--json]",
    "desktop": "simplicio app list|info|doctor|setup|run <name> [--json]",
    "plan": 'simplicio plan "<task>" --repo <path> [--json]',
    "decide": 'simplicio decide "<task>" --repo <path> [--json]',
    "sprint": "simplicio sprint <sprint-path-or-text> --repo <path> [--json]",
    "learn": "simplicio learn from-run <run-id> [--scope project|local|global]",
    "doctor": "simplicio-agent doctor [--fix]",
    "tokio-runtime": "simplicio status [--json] [--watch]",
    "health": "simplicio-agent doctor [--fix]",
    "settings": "simplicio-agent config get|set <key> [<value>]",
}


def list_bridges() -> Dict[str, Dict[str, Any]]:
    """Return the full domain -> {mcp_tool, cli_fallback} routing table.

    This is the machine-readable counterpart of the table in
    `docs/mcp-low-frequency-bridges.md`, and the thing both the docs and
    the desktop app should treat as the source of truth for "MCP tool vs
    CLI fallback available" — see that doc's "Future coverage tracking"
    section.
    """
    return {
        domain: {
            "mcp_tool": tool_name,
            "cli_fallback": _CLI_FALLBACK_COMMANDS.get(domain),
            "status": "mcp" if tool_name else "cli_fallback",
        }
        for domain, tool_name in LOW_FREQUENCY_DOMAINS.items()
    }


def cli_fallback_error(domain: str) -> Dict[str, Any]:
    """Build the explicit CLI-fallback error contract for a P1/P2 domain.

    Every non-MCP domain returns this exact shape so an agent parsing the
    response can distinguish "this simply isn't an MCP tool yet" from a
    real failure — and knows precisely what command to run instead of
    guessing or giving up.
    """
    fallback = _CLI_FALLBACK_COMMANDS.get(domain)
    if fallback is None:
        return {
            "error": f"Unknown low-frequency domain: {domain!r}",
            "known_domains": sorted(LOW_FREQUENCY_DOMAINS),
        }
    return {
        "error": (
            f"{domain!r} is not exposed as an MCP tool — it is an "
            "intentional CLI fallback (see docs/mcp-low-frequency-bridges.md)."
        ),
        "domain": domain,
        "cli_fallback": fallback,
    }


# ---------------------------------------------------------------------------
# cron — read-only status (P0)
# ---------------------------------------------------------------------------

def cron_status() -> Dict[str, Any]:
    """Read-only cron health snapshot: provider, ticker liveness, active jobs.

    Mirrors `hermes_cli.cron.cron_status`'s data (that function only prints
    to stdout) but returns structured JSON instead, so an MCP client can
    check "will my scheduled jobs actually fire" without a shell hop.
    """
    from cron.jobs import (
        get_ticker_heartbeat_age,
        get_ticker_success_age,
        list_jobs,
        TICKER_INTERVAL_SECONDS,
    )
    from gateway.status import get_running_pid

    try:
        from cron.scheduler_provider import resolve_cron_scheduler

        provider = resolve_cron_scheduler().name or "builtin"
    except Exception:
        provider = "builtin"

    jobs = list_jobs(include_disabled=False)
    active_jobs = [
        {
            "id": job.get("id"),
            "name": job.get("name"),
            "next_run_at": job.get("next_run_at"),
            "schedule_display": job.get("schedule_display"),
        }
        for job in jobs
    ]

    result: Dict[str, Any] = {
        "provider": provider,
        "active_job_count": len(active_jobs),
        "active_jobs": active_jobs,
    }

    if provider != "builtin":
        # External provider (e.g. Chronos) fires jobs via a webhook, not the
        # in-process ticker — no heartbeat file is expected. See
        # hermes_cli.cron.cron_status's identical caveat.
        result["will_fire"] = "external_provider"
        return result

    pid = get_running_pid()
    result["gateway_running"] = pid is not None
    result["gateway_pid"] = pid

    if pid is None:
        result["will_fire"] = False
        return result

    hb_age = get_ticker_heartbeat_age()
    ok_age = get_ticker_success_age()
    stale_after = TICKER_INTERVAL_SECONDS * 3 + 20

    result["ticker_heartbeat_age_s"] = hb_age
    result["ticker_success_age_s"] = ok_age

    if hb_age is not None and hb_age > stale_after:
        result["will_fire"] = False
        result["reason"] = "ticker_stalled"
    elif hb_age is not None and ok_age is not None and ok_age > stale_after:
        result["will_fire"] = False
        result["reason"] = "ticks_failing"
    else:
        result["will_fire"] = True

    return result


# ---------------------------------------------------------------------------
# gateway — read-only status (P0)
# ---------------------------------------------------------------------------

def gateway_status() -> Dict[str, Any]:
    """Read-only messaging-gateway liveness check (no lifecycle control)."""
    from gateway.status import get_running_pid

    pid = get_running_pid()
    return {
        "running": pid is not None,
        "pid": pid,
    }


# ---------------------------------------------------------------------------
# hooks — read-only status (P0)
# ---------------------------------------------------------------------------

def hooks_status() -> Dict[str, Any]:
    """Read-only shell-hooks inventory: configured hooks + allowlist state.

    Reuses `agent.shell_hooks.iter_configured_hooks`/`load_allowlist`
    verbatim (the same primitives `hermes_cli.hooks._cmd_list` prints from)
    instead of reimplementing hook-config parsing.
    """
    from agent import shell_hooks
    from hermes_cli.config import load_config

    specs = shell_hooks.iter_configured_hooks(load_config())
    allowlist = shell_hooks.load_allowlist()
    approved = {
        (e.get("event"), e.get("command"))
        for e in allowlist.get("approvals", [])
        if isinstance(e, dict)
    }

    hooks: List[Dict[str, Any]] = [
        {
            "event": spec.event,
            "command": spec.command,
            "matcher": spec.matcher,
            "timeout": spec.timeout,
            "approved": (spec.event, spec.command) in approved,
        }
        for spec in specs
    ]

    return {
        "count": len(hooks),
        "hooks": hooks,
    }


# ---------------------------------------------------------------------------
# CLI fallback — generic tool for every P1/P2 domain (workflow, issue-factory,
# agent, desktop, plan/decide/sprint/learn, doctor/tokio-runtime/health/settings)
# ---------------------------------------------------------------------------

def low_frequency_cli_fallback(domain: str) -> Dict[str, Any]:
    """Look up the CLI-fallback contract for any low-frequency domain.

    Works for every domain in LOW_FREQUENCY_DOMAINS, including the P0 ones
    (which return their MCP tool name instead of an error) — so an agent
    can call this single tool to find out "how do I reach <domain>" without
    needing to already know whether it's MCP or CLI.
    """
    normalized = (domain or "").strip().lower()
    entry = LOW_FREQUENCY_DOMAINS.get(normalized)
    if normalized not in LOW_FREQUENCY_DOMAINS:
        return {
            "error": f"Unknown low-frequency domain: {domain!r}",
            "known_domains": sorted(LOW_FREQUENCY_DOMAINS),
        }
    if entry is not None:
        return {
            "domain": normalized,
            "status": "mcp",
            "mcp_tool": entry,
        }
    return {"domain": normalized, "status": "cli_fallback", **cli_fallback_error(normalized)}


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------

def register_low_freq_tools(mcp: Any) -> None:
    """Register the low-frequency-domain MCP tools on an existing FastMCP server.

    Called from `mcp_serve.create_mcp_server` right before it returns `mcp`.
    Kept as a separate registration function (rather than inlined into
    `mcp_serve.py`) so this module's tools stay independently importable
    and testable, and so future low-frequency domains can be added here
    without growing `mcp_serve.py` itself.
    """

    @mcp.tool(name="cron_status")
    def _cron_status_tool() -> str:
        """Read-only cron health: scheduler provider, ticker liveness, active jobs.

        Returns whether scheduled jobs will actually fire (gateway running +
        ticker heartbeat/success freshness for the built-in provider, or
        "external_provider" when an external scheduler like Chronos owns
        firing). Does not create, modify, or run any job — see
        low_frequency_cli_fallback('cron') for the CLI fallback covering
        add/tick/run/pause/resume/remove.
        """
        from agent._fastjson import dumps

        return dumps(cron_status(), indent=2)

    @mcp.tool(name="gateway_status")
    def _gateway_status_tool() -> str:
        """Read-only messaging-gateway liveness check (pid + running flag).

        Does not start, stop, or restart the gateway — see
        low_frequency_cli_fallback('gateway') for that CLI fallback.
        """
        from agent._fastjson import dumps

        return dumps(gateway_status(), indent=2)

    @mcp.tool(name="hooks_status")
    def _hooks_status_tool() -> str:
        """Read-only shell-hooks inventory: configured hooks + allowlist approval state.

        Does not test, revoke, or run any hook — see
        low_frequency_cli_fallback('hooks') for that CLI fallback.
        """
        from agent._fastjson import dumps

        return dumps(hooks_status(), indent=2)

    @mcp.tool(name="low_frequency_cli_fallback")
    def _low_frequency_cli_fallback_tool(domain: str) -> str:
        """Look up whether a low-frequency domain is an MCP tool or a CLI fallback.

        Domains: cron, gateway, hooks, workflow, issue-factory, agent,
        desktop, plan, decide, sprint, learn, doctor, tokio-runtime,
        health, settings. For CLI-fallback domains, returns the exact
        command to run instead of guessing. See
        docs/mcp-low-frequency-bridges.md for the full classification.

        Args:
            domain: One of the domain names listed above.
        """
        from agent._fastjson import dumps

        return dumps(low_frequency_cli_fallback(domain), indent=2)
