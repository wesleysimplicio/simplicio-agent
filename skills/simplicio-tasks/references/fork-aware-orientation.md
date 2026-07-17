# Fork-aware orientation order

Use this when working on the Simplicio Agent fork.

## Rule

> Canonical source: `AGENTS.md` § "Tool routing" ([ADR-0010](../../../docs/architecture/ADR-0010-runtime-first-execution.md))
> is the single source of truth for the CLI-first/MCP-fallback hierarchy
> (issue #212). This is a task-specific restatement for orientation work,
> not a competing decision — it must never diverge from AGENTS.md.

1. **Hermes reasons and coordinates** — it selects actions, interprets results, and decides; it is not the preferred execution or orientation layer.
2. **Simplicio CLI first** for orientation, reading, searching, and analysis when the task is about understanding the current repo/session state — `simplicio memory`/`simplicio-mapper` orientation attempts the CLI path before anything else.
3. **Simplicio MCP fallback** only when the CLI path is unavailable or an explicit warm MCP path is configured.
4. **Native Hermes tool as temporary capability exception** only for gaps neither the CLI nor MCP surface yet covers — report the gap instead of silently repeating the fallback.

## Why

Simplicio Agent is a fork of Hermes, but the fork-aware default is still CLI-first: `AGENTS.md` § Tool routing (ADR-0010) makes the Simplicio CLI the execution *and* orientation surface, with Hermes reserved for reasoning/coordination and native tools kept as a reported, temporary exception.

## Pitfall

Do not write the workflow as "Hermes-native first" for orientation or fact-finding — that reverses the canonical order in AGENTS.md and was the exact contradiction flagged by issue #212.
