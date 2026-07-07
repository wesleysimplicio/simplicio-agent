# ADR-0003: simplicio-runtime is a managed, pinned dependency — separate repo, unified agent

- Status: accepted
- Date: 2026-07-07
- Related: ADR-0001 (checkpoint mirror), `tools/kernel_binding.py`,
  `tools/runtime_manager.py`, `runtime.lock`, AGENTS.md "Tool routing"

## Context

simplicio-agent is a modified Hermes agent whose execution doctrine is
**Hermes-native tools first** (reading, searching, reasoning, coordination),
**simplicio-runtime kernel second** as the actuator (action gate,
deterministic/mechanical edits, validation, evidence ledger). The bindings
for this exist in `tools/kernel_binding.py`, but until now the kernel was an
*optional PATH discovery*: absent binary -> every binding silently degrades
to "off". A machine can run the agent for weeks with the entire actuator
layer disabled and nothing surfaces it. That contradicts the goal of the
agent and the runtime operating as one system.

Two repos, one system: the runtime stays a **separate repository**
(`simplicio-runtime`, Rust, its own release cadence) — it serves other
consumers (Homebrew, npm, Docker, the desktop bundle). The unification
happens on the agent side, as a dependency contract.

## Decision

1. **`runtime.lock` at the agent repo root pins the kernel.** Schema
   `runtime-lock/v1`: minimum version, release repo, per-platform release
   assets, sibling-checkout path. Updating the runtime the agent depends on
   is now a reviewable commit in *this* repo, not an ambient property of
   whatever is on PATH.

2. **`tools/runtime_manager.py` owns the handshake and the managed
   install.** Resolution order: `HERMES_KERNEL_BIN` env override -> bare
   `simplicio` on PATH -> managed dir `~/.simplicio/bin`. Install
   strategies, in order: `gh release download` of the platform asset
   (macOS/Linux), `cargo build --release` from the sibling checkout (the
   only path on Windows — releases publish no Windows asset). The manager
   **never overwrites a user-managed install** (env/PATH hits are reported
   stale, not replaced).

3. **`kernel_binding.resolve_kernel_bin` falls back to the managed dir**, so
   every existing binding (gate, checkpoint mirror, mechanical edit, orient,
   recall, ledger) lights up from a managed install with zero PATH edits.

4. **`hermes doctor` gains a "Simplicio Runtime Kernel" section.** Absent or
   below-pin kernel is a *fail* with a fix line; `hermes doctor --fix` runs
   the install/update. Degradation stays honest but is no longer silent.

## Consequences

- The agent has a single, auditable answer to "which runtime am I running
  against?" — the lock pin plus the doctor handshake.
- Runtime updates propagate here as lock bumps (a follow-up can automate
  the bump via CI on runtime releases).
- Machines without the kernel now get a loud doctor failure and a one-command
  fix, instead of silent binding degradation.
- Binding mode semantics are unchanged in this step: `auto` still degrades
  when the kernel is genuinely unavailable. Flipping execution-class
  bindings (gate, mechanical edit, ledger) to default `required` is the
  planned next step once managed installs have soaked.
- ADR-0001 is untouched: checkpoints/rollback remain agent-owned
  (shadow-git); the kernel remains an evidence mirror there.

## Alternatives considered

- **Monorepo / vendoring the runtime source into the agent.** Rejected: the
  runtime has independent consumers and release channels (brew, npm,
  Docker, desktop bundle); vendoring forks it. The user explicitly wants
  separate repos with a unified agent.
- **Keep PATH-only discovery and just document it.** Rejected: that is the
  status quo that let whole machines run with the actuator layer silently
  off.
- **Auto-install at session start.** Rejected for this step: a cargo build
  or network download inside session bootstrap is a latency and failure
  hazard. Doctor `--fix` is the explicit, observable entry point; a
  background prewarm can be layered later.
