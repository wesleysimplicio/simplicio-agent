# Fork-aware orientation order

Use this when working on the Simplicio Agent fork.

## Rule

> Canonical source: `AGENTS.md` § "Tool routing" is the single source of
> truth for the CLI-first/MCP-fallback hierarchy (issue #212). This is a
> task-specific restatement for orientation work, not a competing decision.

1. **Hermes-native tools first** for orientation, reading, searching, and analysis when the task is about understanding the current repo/session state.
2. **Simplicio runtime second** for deterministic execution, validation, repeatable edits, and ledgered operations once the task is understood.
3. **Native fallback last** only for gaps the runtime does not yet cover.

## Why

Simplicio Agent is a fork of Hermes. That means the cheapest orientation surface is still Hermes-native, while Simplicio-runtime is the deterministic execution surface.

## Pitfall

Do not write the workflow as "runtime first" when the task begins with repo orientation or fact-finding. That reverses the intended fork-aware order and wastes time on the heavier surface.
