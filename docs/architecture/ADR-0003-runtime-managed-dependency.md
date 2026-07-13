# ADR-0003: simplicio-runtime is a managed, pinned dependency — separate repo, unified agent

- Status: accepted
- Date: 2026-07-07
- Related: ADR-0001 (checkpoint mirror), `tools/kernel_binding.py`,
  `tools/runtime_manager.py`, `runtime.lock`, AGENTS.md "Tool routing"

## Context

simplicio-agent is a modified Hermes agent. The tool-routing hierarchy
(Hermes-native tools first for reading/searching/reasoning/coordination, the
Simplicio CLI second as the actuator for execution/deterministic edits/
validation/evidence, MCP as fallback transport only) is canonical in
`AGENTS.md` § Tool routing (issue #212) — this ADR does not restate or
re-derive that order, it only covers how the kernel *dependency* is pinned
and installed. The bindings for the actuator role exist in
`tools/kernel_binding.py`, but until now the kernel was an
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

3. **Installation only ever happens with explicit consent.**
   `ensure_runtime(install=True)` is reached exclusively through
   `hermes doctor --fix`. Chat startup (`bootstrap_session`, point 7 below)
   performs the `--version` handshake only and **never** installs — an
   unattended network fetch (or, on Windows, an unattended `cargo build`)
   on every session start is a supply-chain and latency hazard the user
   never agreed to. "Managed dependency" means the agent knows what it
   needs and says so loudly; it does not mean the agent silently fetches
   binaries off the network at every startup.

4. **Release downloads are supply-chain-verified, not merely fetched.**
   Each entry in `runtime.lock`'s `assets` map is `{"name": ..., "sha256":
   ...}` (a bare string is still accepted for back-compat, meaning "no
   pinned hash yet"). After `gh release download`, the manager hashes the
   downloaded bytes and compares against the pinned `sha256`:
   - **No pinned hash for this platform's asset -> refuse to install.**
     The download is not attempted blind; `_install_from_release` returns
     "no pinned sha256 for asset — refusing unverified download" and the
     sibling cargo-build strategy is tried instead. Today no asset in the
     repo's `runtime.lock` has its hash pinned yet — this is a deliberate,
     visible TODO (populate `sha256` per release) rather than a silent gap.
   - **Mismatch -> delete the temp file and error**, never install it.
   - The temp download path is unique per process
     (`.{name}.download.{pid}`) and is removed on every failure branch, so
     a concurrent `doctor --fix` in another process can't race or clobber
     it, and failed downloads never leave debris in the managed dir.

5. **The version handshake verifies identity, not just a version-shaped
   substring.** `kernel_version()` anchors a `^simplicio(-runtime)?\s+v?
   X.Y.Z` match at the *start of stdout only* (never stderr). A PATH hit
   that merely shares the kernel's name but prints an unrelated banner
   (e.g. a `Simplicio Agent v0.17.0` CLI collision) fails the handshake
   instead of being mistaken for the kernel — the whole point of pinning a
   version is undermined if "found something that looks like a version
   number" counts as satisfying it.

6. **`kernel_binding.resolve_kernel_bin` falls back to the managed dir**, so
   every existing binding (gate, checkpoint mirror, mechanical edit, orient,
   recall, ledger) lights up from a managed install with zero PATH edits.
   The binary name itself is read from `runtime.lock`'s `kernel` field
   (falling back to the literal `"simplicio"` only if the lock can't be
   read), so the two modules can't drift into disagreeing about what the
   kernel is even called.

7. **`hermes doctor` gains a "Simplicio Runtime Kernel" section.** Absent or
   below-pin kernel is a *fail* with a fix line; `hermes doctor --fix` runs
   the install/update (point 3). Degradation stays honest but is no longer
   silent.

## Consequences

- The agent has a single, auditable answer to "which runtime am I running
  against?" — the lock pin plus the doctor handshake.
- Runtime updates propagate here as lock bumps (a follow-up can automate
  the bump via CI on runtime releases).
- Machines without the kernel now get a loud doctor failure and a one-command
  fix, instead of silent binding degradation.
- **Execution bindings fail closed by default**: `action_gate` and
  `mechanical_edit` default to `required` — the agent always runs *with*
  the runtime, and a missing/broken kernel blocks flagged-dangerous
  execution instead of silently falling back. Read bindings (`orient`,
  `recall`) and evidence mirrors (`checkpoint`, `ledger`) keep `auto`
  honest degradation. `config.yaml` can relax any binding per machine.
- **Windows has no published release asset** (point 2): the only install
  path there is `cargo build --release` from the sibling checkout, which
  `doctor --fix` runs explicitly — it is not attempted from chat startup,
  and not attempted automatically at all. Combined with `required` as the
  default mode, this is a deliberate trade: a fresh Windows checkout with
  no Rust toolchain and no sibling checkout blocks flagged-dangerous
  commands out of the box until the operator runs `doctor --fix` (or
  installs `cargo` and the sibling repo) or relaxes the binding to `auto`
  in `config.yaml`. We accept that friction over the alternative — a
  Windows box quietly running with the actuator/safety layer off and
  nothing surfacing it, which is the exact failure mode this ADR exists to
  close.
- **When `runtime_manager` itself is broken** (import failure, unexpected
  exception during the handshake), `kernel_binding._kernel_verified()`
  fails closed — `(False, "runtime_manager unavailable: ...")` — rather
  than degrading to a presence-only check. A broken dependency-manager
  module is not evidence the kernel on PATH is safe to trust; the whole
  binding contract collapses to the pre-ADR PATH-collision risk if it did.
- **Chat startup only ever handshakes the kernel** (`bootstrap_session`):
  it never downloads or builds anything — see point 3. An absent/stale
  kernel still prints a loud startup warning (with the `hermes doctor
  --fix` instruction) so fail-closed blocks never surprise mid-turn, but
  the fix itself is a separate, explicit step.
- The runtime's MCP server (`simplicio serve --mcp`) remains a separate,
  user-launched surface — this ADR binds the agent to the kernel *binary*,
  not to a persistent server process. **Update (#109, opt-in only):**
  `tools/kernel_binding.py` can additionally spawn and reuse one
  `simplicio serve --mcp --stdio` connection per process
  (`SIMPLICIO_AGENT_KERNEL_WARM=1`) for calls the runtime serves in-process
  (`simplicio_gate` today — simplicio-runtime#2983). This does not revise
  the decision above: warm mode is a latency optimization behind the exact
  same `_run_kernel` contract, with any failure at any layer falling
  through to the classic per-call `subprocess.run` path unchanged. It is
  off by default.
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
- **Auto-install at session start.** Rejected, twice over. First pass of
  this ADR tried a narrower version (release download only, never cargo
  build) at chat startup; an adversarial review flagged it as an
  unattended-network-fetch supply-chain hazard on every process start,
  independent of any sha256 verification. Rejected outright now: `doctor
  --fix` is the sole explicit, observable, consent-bearing install entry
  point. A background prewarm triggered by an explicit user action (not
  ambient chat startup) can be layered later.
- **Trust release downloads without a pinned hash.** Rejected: a `gh
  release download` result is fetched over the network from a repo the
  agent doesn't control the CI supply chain of end-to-end; installing it
  unverified reintroduces exactly the kind of ambient trust ADR-0003 is
  trying to eliminate elsewhere. Refusing to install without a pinned hash
  (falling through to the cargo-build strategy) is more friction than
  blind trust, but the friction is visible and fixable (pin the hash),
  where a supply-chain compromise is neither.
