# Asolaria (JesseBrown1980) Absorption Plan for the Simplicio Ecosystem

**Author:** research pass, 2026-07-01
**Subject:** GitHub user `JesseBrown1980` ("Asolaria" / OP-JESSE-BROWN)
**Scope:** what from JesseBrown1980's public repos is worth absorbing into the
Simplicio ecosystem (Rust runtime `simplicio-runtime` + Hermes-based Python agent
`simplicio-agent`), given what Simplicio already has.

> **Pipeline context:** Hermes Agent → Hermes Turbo (Hermes + performance) →
> Simplicio (Turbo + `Projetos/ai` ecosystem + **Asolaria**). Asolaria is the
> upstream idea-bank for the fabric / addressing / gate / compression layers.
> Much of it is **already absorbed** — this plan is about the *remaining
> non-duplicative* value.

---

## Summary table

| # | Prio | Source repo · feature | Adds | Target in Simplicio | License | Effort | Risk |
|---|------|-----------------------|------|---------------------|---------|--------|------|
| 1 | **P0** | `omni-dispatcher` / `omnicoder` — FEDENV single-parent dispatcher (1000-slot PID-table, 4-lane priority queue, lazy port pool, validator) | A real M2M work-router engine; today Simplicio has the fabric *bus* but no dispatcher/scheduler over it | new crate `simplicio-dispatch` (or module in `simplicio-fabric`) | **NO LICENSE** (all-rights-reserved) — needs explicit grant | M | Med (license) |
| 2 | **P0** | `Harness-edit` — SkillOpt held-out scenario scorer (v2 rollout behavior scoring) | Upgrades Simplicio's existing `simplicio-harness` from text-lint to **rollout/behavior** scoring; gates skill edits on measured improvement | extend `crates/simplicio-harness` | **NO LICENSE** (README = MIT-paper-derived scaffold) | S | Low |
| 3 | **P0** | `ai-memory` — cross-vendor git-markdown handoff wiki + MCP/lifecycle hooks for 10 hosts | Vendor-agnostic session handoff (Claude↔Codex↔Cursor↔Gemini) as plain-markdown git wiki | `simplicio-agent` gateway + `simplicio-compression/cross_memory.rs` | **MIT** ✅ | M | Low |
| 4 | **P1** | `Asolaria-the-full-works...` — 200ns revolver PID emitter (`PIDChainRevolver.next()`) | Deterministic, fork-free agent-id emitter (5M PID/s single-thread); feeds the dispatcher | `crates/simplicio-savings` or `simplicio-agents/seed.rs` | **NO LICENSE** | S | Med (license) |
| 5 | **P1** | `asolaria-whiteroom-engine` — real pluggable scorer/store (never-delete + compact) | Replaces Simplicio's *simulated* whiteroom scorer with a real store interface + deterministic scorer | `crates/simplicio-gnn/whiteroom.rs` | **NO LICENSE** | M | Med (license) |
| 6 | **P1** | `N-Nest-Prime...` — depth-N confabulation gate proof + `.hbp` conformance vectors | Test vectors that prove the corrective gate catches planted faults at *every* level | `crates/simplicio-gate` tests + `crates/simplicio-tests` | **NO LICENSE** | S | Low |
| 7 | **P2** | `asolaria-federation-1024` Host-8 server crates (`vote-quorum`, `cosign-ledger`, `tier-policy`, `gnn-oracle`, `fischer-eval`) | Patterns for quorum voting, tamper-evident cosign ledger, risk-tier policy | study → selective port into `simplicio-security` / `simplicio-gate` | **NOASSERTION** (unclear) | L | High (license + scope) |
| 8 | **P2** | `scala-critical-path-planner` — DAG scheduler / critical-path / slack (concepts only) | Critical-path + slack scheduling algorithm for the exec graph | concept port into `exec_graph` / planner | **MIT** ✅ | M | Low |
| 9 | **P2** | `Docs-Extractor` — Firecrawl+Claude doc-crawl → markdown | AI doc-extraction pattern (Simplicio already has Firecrawl skills) | reference only for `documentation-lookup` flow | **NO LICENSE** | S | Low |

## Status tracking

Machine-readable pending-item list consumed by
`scripts/sync/ecosystem-sync.sh asolaria-absorb`. The summary table above
documents **what** each item is; this section tracks **whether it's been
absorbed yet**. `license_class` mirrors the License column above:
`mit-safe` (safe to vendor with attribution) vs `reimplement-only` (NO
LICENSE / NOASSERTION source — must be reimplemented from the public
spec/README, never copy-pasted).

Only flip a box via `asolaria-absorb --apply --complete <id>` (which
refuses to check off a `reimplement-only` item without an explicit
`--confirm-reimplemented`, and never touches `mit-safe` source files
itself — vendoring, if any, is still a human, reviewed step). Never
bulk-check by hand.

- [ ] 1. P0 · FEDENV single-parent dispatcher (`omni-dispatcher` / `omnicoder`) — reimplement-only (NO LICENSE)
- [ ] 2. P0 · SkillOpt v2 rollout scoring (`Harness-edit`) — reimplement-only (NO LICENSE)
- [ ] 3. P0 · Cross-vendor memory handoff (`ai-memory`) — mit-safe (MIT)
- [ ] 4. P1 · 200ns revolver PID emitter (`Asolaria-the-full-works...`) — reimplement-only (NO LICENSE)
- [ ] 5. P1 · Real whiteroom scorer/store (`asolaria-whiteroom-engine`) — reimplement-only (NO LICENSE)
- [ ] 6. P1 · Depth-N gate conformance vectors (`N-Nest-Prime...`) — reimplement-only (NO LICENSE)
- [ ] 7. P2 · Host-8 server-crate patterns, study only (`asolaria-federation-1024`) — reimplement-only (NOASSERTION)
- [ ] 8. P2 · Critical-path DAG scheduler (`scala-critical-path-planner`) — mit-safe (MIT)
- [ ] 9. P2 · Doc-extraction flow, reference only, nothing to vendor (`Docs-Extractor`) — reimplement-only (NO LICENSE)

### DO NOT absorb (flagged)

| Source | Why not |
|--------|---------|
| `shannon` (fork of KeygraphHQ/shannon) | **AGPL-3.0** — copyleft, incompatible with Simplicio's proprietary/closed binary distribution. Study concepts only; never vendor code. |
| `HRM` (fork of sapientinc/HRM) | Apache-2.0 (fine), but it's a **research training model**, not runtime infra. Out of scope; Simplicio's GNN is architectural, not a trained HRM. |
| `kimi-code`, `intelligent-terminal`, `free-claude-code` | Straight forks of upstream projects (MoonshotAI, Microsoft, Alishahryar1). Nothing Asolaria-original; absorb from the *upstreams* directly if wanted, not via these forks. |
| `35-TB-google-AI-Ultra-migration`, `Asolaria-ASI-*`, `Omni-Asolaria-ASI-OS-*`, `what-is-asolaria...`, `HYPER-BECHS...` | **Doctrine / research-notes / claims repos** (ASI framing, 100B-run "proofs"). No absorbable engine code; high hype-to-code ratio. Read for *ideas*, absorb *nothing* verbatim. |
| Anything carrying HBP/HBI corpus, cosign keys, PID-registration files, receipts | Author already carve-outs these; do not attempt to reconstruct. Security/PII risk. |

---

## Context: what Simplicio ALREADY absorbed from Asolaria

Cross-referencing `simplicio-runtime` crates against the Asolaria repos shows the
core architecture is **already ported**. New work must not duplicate these:

| Simplicio artifact | Asolaria source | Status |
|--------------------|-----------------|--------|
| `crates/simplicio-fabric` (`Omnicoder`, `FabricBus`, HBP packets, `Router`) | `omnicoder---better-than-termux` (8-byte host, M2M fabric) | Absorbed (bus only, not dispatcher) |
| `crates/simplicio-addressing` (`Address` `R.0.1.2`) | Brown-Hilbert `port.port.port` addressing | Absorbed |
| `crates/simplicio-compression/behcs.rs` (256/1024/Hyper tiers) | `Algorithms-of-Asolaria` BEHCS encoding tiers | Absorbed |
| `crates/simplicio-gate/nest.rs` (`NestNode`, `CorrectiveGate`) | `N-Nest-Prime...` watcher-gated nesting | Absorbed (needs test vectors — item 6) |
| `crates/simplicio-harness` (SkillOpt text scorer) | `Harness-edit` (SkillOpt) | Absorbed **v1 only** (needs v2 rollout — item 2) |
| `crates/simplicio-gnn` (`hookwall`, `whiteroom`, `shannon`, `gulp`, `gnn_trio`) | `asolaria-whiteroom-engine`, Shannon civilization, PRISM/gulp | Absorbed **structurally, simulated** (needs real scorer — item 5) |
| `crates/simplicio-claims` (MEASURED/CANON/UNVERIFIED tags) | `AGENT-BRIEF.md` claims-gate discipline | Absorbed |

**Gaps (the delta this plan targets):** the *dispatcher/scheduler* over the bus,
the *PID emitter* that feeds it, real *whiteroom scoring* (currently simulated),
SkillOpt *v2 rollout* scoring, cross-vendor *memory handoff*, and gate *conformance
vectors*.

---

## Repository inventory (68 repos, relevant subset)

Enumerated via `gh api users/JesseBrown1980/repos --paginate`. 68 public repos
total; ~40 are the 2026 "Asolaria" cluster (mostly JavaScript, low stars 0–25,
active push dates 2026-06/07), the rest are older client work and upstream forks.

Highest-signal originals:

- **`asolaria-behcs-256`** (JS, 25★, MIT) — the federation toolkit index; 205-item
  SMP plan; envelope v1, local-LLM wrapper, agent manager, identity, drift,
  Shannon roles, cosign. Mostly a **map**; concrete engines live in the sibling
  repos below.
- **`omni-dispatcher`** (JS, no license) — **FEDENV single-parent dispatcher** →
  item 1.
- **`omnicoder---better-than-termux`** (Rust, no license) — the 8-byte-host
  runtime; bus already in `simplicio-fabric`, dispatcher not.
- **`asolaria-federation-1024`** (Rust, NOASSERTION) — `no_std` kernel + 10 Host-8
  server crates → item 7 (study).
- **`asolaria-whiteroom-engine`** (JS, no license) — real scorer/store → item 5.
- **`Harness-edit`** (Py, no license) — SkillOpt scorer v1+v2 → item 2.
- **`N-Nest-Prime...`** (JS, no license) — depth-N gate proof → item 6.
- **`Asolaria-the-full-works-200-nanoseconds-agent-emitter-plus-`** (JS, no
  license) — revolver PID emitter → item 4.
- **`ai-memory`** (Rust, **MIT**) — cross-vendor handoff wiki → item 3.
- **`scala-critical-path-planner`** (Scala, MIT) — DAG/critical-path → item 8.
- **`Algorithms-of-Asolaria`** (no license) — the math catalog; already the source
  for addressing + BEHCS. Reference, not re-absorb.

Forks (absorb from upstream, not these): `shannon` (AGPL — avoid), `HRM`
(Apache), `kimi-code` (MIT), `intelligent-terminal` (MIT), `free-claude-code`
(MIT), `OpenMythos`.

---

## Detailed items

### P0

#### 1. FEDENV single-parent dispatcher — `omni-dispatcher` / `omnicoder`
- **What it adds:** Simplicio has the M2M *bus* (`simplicio-fabric`) but no
  *dispatcher* that owns a PID-table and routes envelopes to workers with a
  priority queue and lazy per-slot ports. The omni-dispatcher is a clean,
  self-contained engine: single loopback HTTP ingress `:4950`, 1000-slot in-memory
  PID-table (`bySlotId/byHCoord/byPid`), 4-lane priority queue (`apex/high/normal/low`)
  drained by a worker pool on a 5ms tick, lazy port pool `:4951–5950` with LRU
  evict + idle sweep, a `validator.mjs` FEDENV-v1 gate (11 required fields,
  target-prefix whitelist, payload ≤64KB), and a route table.
- **Integration target:** new crate `crates/simplicio-dispatch` sitting on top of
  `simplicio-fabric`'s `FabricBus`, reusing `simplicio-addressing::Address` for the
  H-coord index and `simplicio-gate` for the FEDENV validator. Wire it as the
  scheduler for `simplicio-agents` pool spawning.
- **License:** **NO LICENSE FILE** → all-rights-reserved by default. **Do not
  vendor bytes.** Re-implement the *pattern* in Rust from the README/spec (which is
  public and descriptive), or obtain an explicit MIT grant from the author. Flag
  for legal check before any copy-paste.
- **Effort:** M. **Risk:** Med — pattern is safe to reimplement; verbatim copy is
  not (license). Loopback-only bind + payload cap should be preserved (good
  security posture).

#### 2. SkillOpt v2 rollout scoring — `Harness-edit`
- **What it adds:** Simplicio's `simplicio-harness` currently does **v1 text-lint**
  (required/forbidden phrase presence). `Harness-edit` also defines **v2 rollout
  behavior scoring**: each scenario carries a `prompt` and a `rubric` with
  `apply_any` (correct-behavior markers) / `fail_any` (old-mistake markers), scored
  against an actual agent *response*, not just the skill text. This closes the
  SkillOpt loop (a skill edit is accepted only if it improves held-out behavior).
- **Integration target:** extend `crates/simplicio-harness` with the v2 scenario
  schema + a rollout scorer that consumes agent responses (via the Python agent's
  eval harness). Feed rejected reports back as new scenarios (the "rejected buffer").
- **License:** README frames it as public-safe scaffold derived from the SkillOpt
  paper (arXiv 2605.23904); no LICENSE file. The *schema + scoring rules* are
  described in the README and are safe to reimplement. Reimplement, don't copy.
- **Effort:** S. **Risk:** Low.

#### 3. Cross-vendor memory handoff — `ai-memory` (**MIT**)
- **What it adds:** A vendor-neutral, git-tracked **plain-markdown wiki** that
  captures every prompt/tool-call/decision and, at session end, rewrites the
  relevant pages into a "where you left off" handoff — readable by the *next*
  agent regardless of vendor (Claude Code, Codex, OpenCode, Cursor, Gemini, OMP,
  OpenClaw). Ships MCP config + lifecycle hooks per host. Simplicio has neural
  memory (`simplicio_memory`) and `cross_memory.rs`, but not a **grep-able,
  Obsidian-openable, vendor-agnostic markdown handoff** — which fits Simplicio's
  local-first, MCP-first doctrine and the user's Obsidian auto-log habit.
- **Integration target:** absorb the handoff/rewrite pattern into
  `simplicio-agent` (gateway session lifecycle) and reconcile with
  `simplicio-compression/cross_memory.rs`. Keep the markdown-in-git store as an
  export/interop layer alongside the SQLite neural memory (not a replacement).
- **License:** **MIT** ✅ — fully compatible. Can vendor with attribution.
- **Effort:** M. **Risk:** Low. Only real friction is de-duplicating against the
  existing SQLite memory so there aren't two competing stores.

### P1

#### 4. 200ns revolver PID emitter — `Asolaria-the-full-works...`
- **What it adds:** `PIDChainRevolver.next()` emits a Brown-Hilbert / `sha16(seed)`
  PID every ~200ns (≈5M PID/s single-thread) with **zero OS processes**
  (VirtualPointer-dominant, no fork/exec). This is the *source* that feeds the
  dispatcher (item 1). Simplicio's `simplicio-agents/seed.rs` + `simplicio-savings`
  have identity/seed helpers but no high-throughput deterministic emitter.
- **Integration target:** `crates/simplicio-savings` (throughput lane) or a small
  `emitter` module in `simplicio-agents`, emitting `simplicio-addressing::Address`
  + `sha16` PIDs, consumed by `simplicio-dispatch` (item 1).
- **License:** **NO LICENSE** — reimplement the algorithm (it's a `sha256(seed)`
  chain + packed typed-array analogue → a Rust `[u8;8]` slot). Don't copy JS.
- **Effort:** S. **Risk:** Med (license) — algorithm is trivial and safe to
  reimplement from the description; the "1.16T agents/s" figure is marketing, ignore.

#### 5. Real whiteroom scorer/store — `asolaria-whiteroom-engine`
- **What it adds:** Simplicio's `simplicio-gnn/whiteroom.rs` is explicitly
  **simulated** (in-memory sizes, `KEEP=full / COMPACT=10%`). The Asolaria engine
  defines a **real pluggable store interface** (`put/get/scanByPID/compact` where
  compact = *move to compacted, never delete*) and a **pluggable scorer**
  (`DeterministicScorer` offline + `L0GnnScorer` live). Absorbing the interface
  turns Simplicio's simulated whiteroom into a real, testable, never-delete curation
  store with a deterministic default scorer.
- **Integration target:** rework `crates/simplicio-gnn/whiteroom.rs` to a
  trait-based store + scorer; keep `DeterministicScorer` as default, leave a hook
  for `simplicio-gnn`'s trio as the real scorer.
- **License:** **NO LICENSE** — reimplement the interface (it's a 4-method store
  trait; trivial). Don't copy the `.mjs`.
- **Effort:** M. **Risk:** Med (license). The "never-delete/compact" discipline is
  the valuable idea and is safe to reimplement.

#### 6. Depth-N gate conformance vectors — `N-Nest-Prime...`
- **What it adds:** The nesting gate (`simplicio-gate/nest.rs`) is already ported,
  but Asolaria's repo ships **empirical proof vectors**: a planted confabulation at
  *every* level 1–7 (prime) is caught at that exact level, with sealed `.hbp`
  outputs. Absorbing these as **test fixtures** hardens Simplicio's gate against
  regressions and proves depth-independence.
- **Integration target:** `crates/simplicio-gate` tests + `crates/simplicio-tests`
  — reproduce the "plant a fault at every level, assert caught at that level"
  property test.
- **License:** **NO LICENSE** — reproduce the *test methodology* (plant fault →
  assert exact-level catch), don't copy the `.hbp` byte outputs.
- **Effort:** S. **Risk:** Low.

### P2

#### 7. Host-8 server-crate patterns — `asolaria-federation-1024`
- **What it adds:** 10 Rust Host-8 server crates. The non-duplicative ones worth
  *studying* (not wholesale porting): `vote-quorum` (quorum voting for gated
  actions), `cosign-ledger` (tamper-evident Merkle cosign chain — Simplicio already
  has an HBP evidence chain, cross-check), `tier-policy` (risk-tier policy — maps to
  `simplicio-gate` classify), `gnn-oracle`, `fischer-eval` (Bobby-Fischer eval
  kernel). Most overlap Simplicio's existing gate/security; extract only genuinely
  new patterns (quorum voting is the clearest candidate).
- **Integration target:** selective concept port into `simplicio-security` /
  `simplicio-gate`. **Study first, port narrowly.**
- **License:** **NOASSERTION** (GitHub couldn't resolve a standard license) →
  treat as all-rights-reserved. Concepts only.
- **Effort:** L. **Risk:** High — large surface, unclear license, heavy overlap
  with existing crates. Easy to over-absorb. Keep to quorum-voting if anything.

#### 8. Critical-path DAG scheduler — `scala-critical-path-planner` (**MIT**)
- **What it adds:** Deterministic topological ordering, schedule calculation,
  **slack** surfacing, and representative critical-path extraction for branching
  DAGs, plus a task DSL. Concept fit for Simplicio's `exec_graph` / conditional
  execution graph (the LangGraph-parity work in the ecosystem absorption tracker).
- **Integration target:** concept port of the critical-path + slack algorithm into
  the exec-graph planner (Rust). It's Scala, so this is a **re-implementation**, not
  a vendor.
- **License:** **MIT** ✅ (algorithm reuse fine even if reimplemented in Rust).
- **Effort:** M. **Risk:** Low.

#### 9. Doc-extraction flow — `Docs-Extractor`
- **What it adds:** A Firecrawl + Claude documentation-crawl → markdown generator
  (Deno backend + React UI). Simplicio already has Firecrawl skills and a
  `documentation-lookup` flow, so this is **reference only** — confirms the
  crawl→structured-markdown pattern, nothing to vendor.
- **Integration target:** none (validation of existing approach).
- **License:** NO LICENSE. **Effort:** S. **Risk:** Low (don't absorb code).

---

## License / security red flags (consolidated)

1. **Most Asolaria originals have NO LICENSE FILE** → all-rights-reserved by
   default. Items 1, 4, 5, 6, 9 must be **reimplemented from public README/spec**,
   never copy-pasted, or gated on an explicit permissive grant from the author
   (same person may be willing given the collaboration framing).
2. **`shannon` is AGPL-3.0** — hard incompatible with Simplicio's closed-binary
   distribution. **Do not vendor.** Study concepts only.
3. **`asolaria-federation-1024` is NOASSERTION** — unresolved license; treat as
   all-rights-reserved.
4. **MIT-clean and safe to vendor with attribution:** `ai-memory`,
   `scala-critical-path-planner`, `asolaria-behcs-256`, `kimi-code`,
   `intelligent-terminal`, `free-claude-code` (forks).
5. **Security:** all Asolaria repos already carve out keys/seeds/tokens/HBP
   corpus/PID-registration/receipts. **Do not attempt to reconstruct** any of that.
   The dispatcher's loopback-only bind + 64KB payload cap + graceful drain are
   *good* patterns to keep. The "100B-run / 1.16T agents/s / ASI" claims are
   marketing framing — absorb engines, ignore the hype metrics.

## Recommended sequencing

1. **P0-2 (SkillOpt v2)** and **P0-3 (ai-memory, MIT)** first — lowest risk, one is
   fully license-clean, both give immediate agent-quality wins.
2. **P0-1 (dispatcher)** + **P1-4 (emitter)** together — they compose; reimplement
   in Rust behind the existing `simplicio-fabric` bus.
3. **P1-5 (real whiteroom)** + **P1-6 (gate vectors)** — hardens the already-ported
   GNN/gate layer from "simulated" to "real + proven".
4. **P2** only after P0/P1 land, and only the narrowly non-duplicative slivers
   (quorum voting, critical-path/slack).
