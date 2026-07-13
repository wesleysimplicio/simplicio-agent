# MCP Low-Frequency Bridges — cron, gateway, workflow, issue-factory e afins

Issue: #99. Refs: #20, #21, #44, #45.

`docs/SIMPLICIO_COMMAND_SURFACE.md` lists the full `simplicio` CLI surface
(111 signatures). Only a small slice of that surface has an MCP tool today
(`mcp_serve.py`'s messaging-bridge tools + `computer_use`). Everything else
is a **CLI fallback**: an agent driving Simplicio through an MCP client can
still reach these commands via `simplicio shell -- <cmd>` or the gated
`simplicio exec "<subcommand>"` router, just not as a first-class typed MCP
tool. That is fine for rare commands — it stops being fine when an agent
can't tell the difference between "not exposed yet" and "doesn't exist",
which is the gap this doc (and `mcp_low_freq_bridges.py`) closes.

## Classification

Priority: **P0** = becomes a real MCP tool in this pass (Phase 2). **P1** =
CLI fallback today, good MCP candidate later (needs auth/side-effect design
first). **P2** = CLI fallback only, low value as MCP (destructive, purely
interactive, or redundant with an existing tool).

| Domain | Commands | Priority | MCP tool | Why |
| --- | --- | --- | --- | --- |
| **cron** | `cron status\|list` | P0 | `cron_status` | Read-only, safe, high agent value (checking scheduled jobs without a shell hop). |
| **cron** | `cron add\|tick\|run\|pause\|resume\|remove` | P2 | — (CLI fallback) | Mutates scheduled jobs; needs an approval story before it's a blind MCP call. |
| **gateway** | `gateway status` (via `agents status`/`doctor`) | P0 | `gateway_status` | Read-only liveness check for the messaging gateway. |
| **gateway** | `gateway setup\|start\|stop\|restart` | P2 | — (CLI fallback) | Process lifecycle; wrong transport for an MCP stdio client to own. |
| **workflow** | `workflow list\|status\|events\|failures` | P0 | `workflow_status` | Read-only introspection into a running/finished workflow. |
| **workflow** | `workflow run\|resume\|retry\|watch` | P1 | — (CLI fallback) | Side-effecting; candidate once workflow tools get a shared approval gate. |
| **issue-factory** | `issue-factory discover\|metrics\|benchmark` | P0 | `issue_factory_status` | Read-only discovery/metrics, mirrors `workflow_status`'s shape. |
| **issue-factory** | `issue-factory run\|claim\|pr-handoff\|comment\|mvp` | P1 | — (CLI fallback) | Opens PRs / claims issues — real-world side effects, needs the same gate as `messages_send`. |
| **agent** | `agents status` | P0 | *(covered by `gateway_status`)* | Same read-only liveness data as gateway status; one tool, not two. |
| **agent** | `agents delegate\|children\|pause\|resume\|interrupt` | P2 | — (CLI fallback) | Controls other running agents; too much blast radius for a first pass. |
| **desktop** | `computer-use *` | done | `computer_use` (existing) | Already bridged with a safety gate (`_computer_use_mcp_refusal`). |
| **desktop** | `app list\|info\|doctor\|setup\|run` | P2 | — (CLI fallback) | Desktop app-launcher surface; low call volume, no read-only subset worth a tool yet. |
| **plan/decide/sprint/learn** | `plan`, `decide`, `sprint`, `learn from-run` | P1 | — (CLI fallback) | Each spawns real planning/execution work (tokens, possibly PRs); needs the same review as `run`/`validate` before a blind MCP call. |
| **doctor/hooks/tokio-runtime/health/settings** | `doctor`, `hooks list\|test\|revoke\|doctor` | P0 | `doctor_status` | Read-only diagnostics — the single highest-value "why did that MCP call fail" tool for an agent debugging its own environment. |
| **doctor/hooks/tokio-runtime/health/settings** | `status` (tokio/perf), `settings` (config get/set) | P2 | — (CLI fallback) | `status --watch` is a streaming TUI concern; `settings` writes config — mutating, needs a review gate first. |

## Routing rule (how an agent decides MCP vs CLI)

1. Check `mcp_low_freq_bridges.list_bridges()` (or the table above) for the
   domain. If a tool name is listed, call it — it is tested and stable.
2. If the domain is P1/P2, or the operation mutates state, fall back to
   `simplicio shell -- <command>` or `simplicio exec "<subcommand>"`. Both
   are CLI fallback paths, always available, and are not "missing MCP
   coverage" — they are the intended second tier of this contract.
3. If a P0 tool call fails, it returns `{"error": ..., "cli_fallback": "..."}`
   (see `mcp_low_freq_bridges.cli_fallback_error`) with the exact CLI command
   to run instead — never a bare stack trace.

## Future coverage tracking

Each row above maps 1:1 to:

- a CLI command (from `docs/SIMPLICIO_COMMAND_SURFACE.md`),
- a domain (cron / gateway / workflow / issue-factory / agent / desktop /
  plan-decide-sprint-learn / doctor-hooks-tokio-health-settings),
- and either an MCP tool name (P0, implemented in `mcp_low_freq_bridges.py`)
  or an explicit "CLI fallback" marker (P1/P2).

When a P1 command graduates to P0, move its row's Priority column to `P0`,
add the tool to `mcp_low_freq_bridges.py` and its name to
`mcp_low_freq_bridges.list_bridges()`, and add tests to
`tests/test_mcp_low_freq_bridges.py`. Grepping this table for `P1`/`P2` is
the authoritative "what's left" list — do not let a second, drifting list
of TODOs grow elsewhere.
