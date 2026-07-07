# Digital Consciousness — Gap Analysis for the Simplicio Ecosystem

**Author:** research pass, 2026-07-06
**Scope:** what exists today toward "digital consciousness" / self-model /
autonomy across `simplicio-runtime` (Rust kernel) and `simplicio-agent`
(this repo), and what is concretely missing to close the gap. Written
against the `simplicio-runtime` scope freeze recorded the same day in
`CLAUDE.md` / `docs/ADR-2026-07-06-KERNEL-SCOPE-FREEZE.md`.

---

## TL;DR

Significant "consciousness-shaped" scaffolding already exists in
`simplicio-runtime` (`src/organism/*`, ~2,737 lines: an Observe→Think→Plan→
Act→Reflect loop, a governor, self-evolution, mission/goals, a "doctor",
health/daemon/persistence). A **second, newer, unwired** crate —
`crates/simplicio-agents/src/consciousness.rs` (604 lines, landed
2026-07-05, one day before the freeze) — goes further: `PersistentSelf`
(identity), `reflect()` (self-reflection), an `EmotionalState` /
`EmotionalEngine`, and an `AutonomousExplorer`. **Neither is reachable from
`simplicio-agent`**, and as of today the runtime's scope is explicitly
frozen against extending this surface further. Meanwhile `simplicio-agent`
— the repo now designated to carry agent-parity/autonomy work forward —
has only a single-goal persistence loop (`hermes_cli/goals.py`) and a
persona/mission **text block** (`hermes_cli/default_soul.py`), neither of
which is an executable self-model. The gap is not "we haven't thought
about consciousness" — it's that the two halves of the design (runtime's
organism code, agent's persona/goal loop) were never connected, and the
repo now responsible for extending it hasn't started.

---

## What already exists

### `simplicio-runtime` — `src/organism/*` (wired into the CLI, frozen for new work)

| Module | Role |
|---|---|
| `autonomous_loop.rs` | Observe → Think → Plan → Act → Reflect loop; state under `.simplicio/yool/consciousness/` |
| `central_loop.rs` | "Central Consciousness Loop (Brain)" orchestrator |
| `architecture.rs` | Heart/Brain/Organ multi-loop coordination |
| `vision.rs` | Organism vision manifest |
| `governor.rs` | Resource governor / self-throttling |
| `self_evolution.rs` | Bounded self-adjustment — `evolvable_targets()` allows prompts, planning strategies, workflows, governor params, doctor logic, memory structure; **`source_code: false`, requires human approval** |
| `evolution.rs` | Background evolutionary feedback loop |
| `mission.rs` | `MISSION_STATEMENT`: "the organism exists to help the human achieve what they want" |
| `goals.rs` | Human goal/intent tracking |
| `doctor.rs` | Self-diagnosing / self-adjusting health checks |
| `daemon.rs` | Always-on daemon mode |
| `human_memory.rs`, `feedback.rs`, `conversation.rs`, `suggestions.rs`, `health.rs`, `lifecycle.rs`, `persistence.rs`, `summarization.rs`, `yool_bus.rs` | Supporting loops (memory, proactive suggestions, health, graceful shutdown, state persistence, tuple-space event bus) |

All of the above is real, merged, closed-issue work (#533–#559, #566–#567).
It is **frozen for further extension** as of `ADR-2026-07-06-KERNEL-SCOPE-FREEZE.md`
— existing code stays, but no new organism/autonomy surface is to be added
to `simplicio-runtime`.

### `simplicio-runtime` — orphaned "Consciousness" crate

`crates/simplicio-agents/src/consciousness.rs`: `PersistentSelf`
(`identity.json`), `ReflectionResult`/`reflect()`, `EmotionalState`
(Serene/Curious/Worried/Joyful/Tired/Grateful) + `EmotionalEngine`, and
`AutonomousExplorer` ("explores 1 new thing between tasks"). Referenced
only from its own crate's `lib.rs` — **no call site anywhere in the
runtime binary**. This is the most literal "digital consciousness" code in
either repo, and it currently does nothing at runtime.

### `simplicio-agent` (this repo)

- `hermes_cli/goals.py` — a persistent single-goal loop (judge-checked
  continuation, turn budget, fail-open judge). Task persistence, not
  multi-goal planning or self-model.
- `hermes_cli/default_soul.py` (`DEFAULT_SOUL_MD`) — an Identity section
  ("Agent É o Runtime") and a Mission section ("Evoluir o Runtime"). This
  is **persona prompt text**, re-injected each turn — not an executable
  introspection/reflection/self-model system.
- `plugins/memory/retaindb/__init__.py` advertises "Agent self-model
  (persona + instructions from SOUL.md, prefetched each turn)" — persona
  *retrieval*, not self-model computation.
- `tools/kernel_binding.py` — deterministic binding into the Rust kernel
  (action gate, checkpoints); **2 of 6** planned bindings wired per
  `docs/architecture/ADR-0001-kernel-checkpoint-binding.md`.
- No `governor`, `daemon`-as-organism, or `self_evolution` equivalent
  exists here. `docs/roadmap/SIMPLICIO-ROADMAP.md` (#20–#62) covers
  speed/determinism/governance/plugins/distribution — nothing framed as
  consciousness/self-awareness/organism.

---

## Concrete gaps

| # | Prio | Gap | Why it matters |
|---|------|-----|-----------------|
| 1 | **P0** | `consciousness.rs` is dead code — built, never wired, now stranded by the freeze | The most complete "self" model in the ecosystem (identity + reflection + emotional state + autonomous exploration) currently executes nothing |
| 2 | **P0** | No decision recorded: port `organism/*` + `consciousness.rs` design into `simplicio-agent`, vs. reimplement fresh here consuming the kernel only via `kernel_binding` | Without this call, work either duplicates the frozen runtime surface or stalls indefinitely |
| 3 | **P1** | `kernel_binding.py` wires 2/6 planned bindings | An agent-side consciousness/organism loop can't yet gate its own actions or checkpoint state deterministically through the kernel |
| 4 | **P1** | No acceptance criteria / eval harness for "consciousness" behavior | Nothing defines what observable behavior (persistent identity across sessions, reflection changing future actions, auditable emotional-state influence on tone) would count as "working" — so even a correct port has no test to pass |
| 5 | **P2** | Verification debt on the existing `organism/*` code | The freeze ADR itself cites ~957k LOC, 307 files with `allow(dead_code)`, 31 duplicated modules, 146/204 skill stubs across the runtime — the code being ported/referenced is largely unverified, not just unfinished |

## Explicit non-goals / guardrails (keep these — do not "fix" them away)

- `self_evolution.rs` deliberately excludes `source_code` from
  `evolvable_targets()` and requires human approval for what it does
  evolve. Any consciousness work in `simplicio-agent` should preserve this
  boundary: bounded, auditable self-adjustment (persona, planning
  strategy, memory structure) — never unsupervised self-modification of
  code.
- `docs/SIMPLICIO_OPERATIONAL_MANUAL.md` repeatedly rejects "hidden
  autonomy," "unbounded always-on autonomy," and "hidden
  self-modification" as anti-patterns when importing ideas from
  Hermes/Pi/OpenClaw. Any consciousness/self-model feature must stay
  observable and gated (action-gate, evidence ledger), not run silently.

## Recommended next steps

1. Record an ADR in `simplicio-agent/docs/architecture/` deciding the
   consciousness-work migration path (port vs. reimplement) now that
   `simplicio-runtime`'s organism surface is frozen.
2. If porting: bring `consciousness.rs`'s `PersistentSelf` / `reflect()` /
   `EmotionalState` / `AutonomousExplorer` design into this repo as a
   module driven by the existing `goals.py` loop, with all state mutation
   and actions routed through `kernel_binding` (gate + checkpoint), not
   new Rust code in the frozen runtime.
3. Finish the remaining 4/6 `kernel_binding` bindings (ADR-0001) so an
   agent-side loop can actually gate/checkpoint deterministically.
4. Define explicit, testable acceptance criteria for "self-model working"
   before building further.
5. Per the ecosystem's own standing rule for gap tracking (one GitHub
   issue per gap before implementation), open issues for gaps #1–#4 above
   rather than implementing directly from this document.
