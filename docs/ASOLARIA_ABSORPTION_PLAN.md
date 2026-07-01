# Asolaria Absorption Plan

Tracks items to be absorbed from the **Asolaria / JesseBrown1980** line into
Simplicio via the ecosystem sync pipeline. This file is read (read-only) by
`scripts/sync/ecosystem-sync.sh asolaria-absorb`, which lists every **unchecked**
task-list item below as "pending". Nothing here is applied automatically yet —
the `asolaria-absorb` subcommand is a placeholder hook.

## How this file is consumed

- Pending item = an unchecked GitHub task-list bullet: `- [ ] ...`.
- Absorbed item = a checked bullet: `- [x] ...`.
- The subcommand prints line numbers + text for every pending item so a human
  (or a follow-up automation) can act on them deliberately.

## Source

- Upstream line: Asolaria / JesseBrown1980.
- Absorption direction: Asolaria -> Simplicio (additive; same newer-file-safe
  discipline as the Turbo perf pull once wiring lands).

## Pending items

<!-- Add concrete, reviewable items below. Keep each one self-contained. -->

- [ ] Inventory the Asolaria modules and classify each as perf / feature / infra.
- [ ] Decide per-module: absorb additively, adapt, or intentionally exclude.
- [ ] Define the canonical Asolaria copy list (mirror of `PERF_PATHS`).
- [ ] Add targeted test coverage for any absorbed Asolaria module.
- [ ] Wire the copy list into `asolaria-absorb` behind `--apply` (currently a no-op).

## Absorbed items

<!-- Move items here (checked) once they land in Simplicio, with a CHANGELOG ref. -->
