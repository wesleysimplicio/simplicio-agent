# ADR-0001: kernel checkpoint binding is a mirror, not a replacement

- Status: accepted
- Date: 2026-07-03
- Related: issue #20 (F2 — simplicio-runtime kernel binding), `tools/checkpoint_manager.py`, `tools/kernel_binding.py`

## Context

Issue #20 asks the agent to make `simplicio` (the runtime kernel) the
deterministic spine for the conversation loop, including checkpoint/undo. It
explicitly leaves the choice open: "integrar com `tools/checkpoint_manager.py`
existente (decidir: wrapper do kernel ou substituição; documentar a escolha
como ADR)."

`tools/checkpoint_manager.py` is a mature, purpose-built subsystem:

- A **single shared shadow git store** (`~/.hermes/checkpoints/store/`) that
  content-addressably deduplicates blobs across every project and worktree —
  a design point called out explicitly in its module docstring as the fix
  for a real problem (per-project shadow repos burning ~40 MB each).
- Per-project retention, auto-prune, and a size-cap pass tuned for this
  agent's turn-by-turn snapshot cadence.
- Already wired into every file-mutating tool path (`write_file`, `patch`,
  destructive `terminal` calls) via `ensure_checkpoint()`, one per
  conversation turn.

The kernel's own `simplicio checkpoint` command is a general-purpose
primitive for the runtime ecosystem, not something written for Hermes'
per-turn, per-worktree, dedup-across-projects snapshot cadence.

## Decision

**The kernel does not own or replace the snapshot mechanism.**
`tools/checkpoint_manager.py`'s shadow-git store stays the checkpoint of
record: it is what `restore()`/`diff()`/`list_checkpoints()` operate on, and
it is what rollback in this codebase means.

The kernel binding (`tools/kernel_binding.mirror_checkpoint`) is a
**best-effort mirror**: after `CheckpointManager.ensure_checkpoint()`
successfully takes a real snapshot, it fires a non-blocking, never-raising
call to `simplicio checkpoint record` so the event lands in the kernel's HBP
evidence ledger alongside the agent's other kernel-gated actions (per
binding 6, "Evidência no ledger"). If the kernel is absent, slow, or errors,
the real checkpoint has already happened — the mirror call only adds
evidence, it is never on the critical path for rollback.

## Consequences

- No regression risk to the existing (well-tested, GC'd, size-capped)
  checkpoint system — it is untouched except for one additive call site.
- Rollback/restore semantics do not change and do not depend on the kernel
  being installed.
- The kernel's evidence ledger gets a record of every checkpoint taken,
  satisfying the "tamper-evident by construction" goal from the issue,
  without the agent depending on the kernel for its own safety net.
- If the kernel's checkpoint primitive later grows a capability
  `checkpoint_manager.py` doesn't have (e.g. cross-machine sync), that is a
  new ADR, not a silent reversal of this one.

## Alternatives considered

- **Replace `checkpoint_manager.py` with kernel calls.** Rejected: would
  make every write-tool call in this agent depend on an external binary
  being installed and healthy, is a hard regression versus the current
  zero-dependency shadow-git approach, and throws away real, tested
  dedup/retention logic to reimplement it worse inside a subprocess
  boundary.
- **Two independent checkpoint systems, user picks one.** Rejected: splits
  rollback into two inconsistent stores; a user restoring from the wrong one
  loses data silently.
