# Simplicio Agent — Unified Roadmap

> **Issue:** #25 — [MESTRA] Simplicio Agent: A Unificacao Definitiva
> **Status:** Planning — supersedes and unifies the Hermes Turbo × Simplicio Runtime × Asolaria convergence tracks.
> **Spec version:** 1.0 (2026-07-03)

## Vision

**One product — `simplicio-agent` — the fastest, most deterministic, and most
guaranteed agent in the world**, merging three lineages:

| Pillar | Source | What it brings |
|---|---|---|
| **Speed** | Hermes Turbo Agent | Streaming, hot-paths, prewarm, conversation latency |
| **Determinism** | Simplicio Runtime (Rust kernel) | Action gate, checkpoints/undo, mechanical zero-token editing, HBP evidence ledger, local ladder 64→600 |
| **Guarantee by construction** | ASOLARIA | N-Nest watcher-gate (`reported == recomputed`), "possibility cheap and action gated", bounded recursion, never-explode caps, signed ledger |

## What already exists

- ✅ Hermes Turbo perf: `_fastjson.py`, `_hermes_fast.py` (measured dispatch),
  `rust_ext/` (PyO3 bridge), `async_dag/`, conversation compression — all
  byte-identical to `hermes-turbo-agent` HEAD
- ✅ F1 inventoried (#19): full diff matrix committed at
  `docs/simplicio-import/turbo-import-matrix.md`; 3 import candidates tracked as
  #68, #69, #70 with A/B benchmarks defined
- ✅ F2 kernel binding (#20): `tools/kernel_binding.py` with 2/6 bindings
  wired (action gate + checkpoint mirror), ADR-0001 documenting the
  checkpoint decision
- ✅ TOON at the tool-executor chokepoint (#16): cache-safe session-pinned
  flag, `toon_boundary.py` converter, savings telemetry revived, conformance
  golden-corpus adopted
- ✅ ADR-0002: provider-mode contract (3 modes: standalone / tool / delegated)
- ✅ PR #77: Simplicio Agent is CLI-only — web/website/desktop archived

## Phases

### Phase 1 — Foundation (P0) — Q3 2026

| Issue | What | Status |
|---|---|---|
| #27 | MCP Server as central bus (runtime↔agent) | Not started |
| #29 | Unified LLM router (local + remote) | Not started |
| #30 | Unified gateway (Discord + Telegram + CLI) | Not started |

### Phase 2 — Orchestration (P1) — Q3 2026

| Issue | What | Status |
|---|---|---|
| #20 | F2 kernel binding (remaining 4 bindings) | Partial (2/6 done) |
| #21 | F3 N-Nest watcher-gate | Partial (bounded local evidence gate; integrations pending) |
| #22 | F4 ASOLARIA/economy (handles, tail-O(1)) | Not started |
| #31 | Unified skills system | Not started |
| #32 | BEHCS multi-agent supervisors | Not started |
| #35 | Shannon adversarial pipeline | Not started |
| #36 | Addressing geometry (REALMATHPOS, FNV-1a64, sha16) | Not started |
| #37 | Host-8 binary protocol | Not started |
| #38 | ai-memory cross-vendor handoff | Not started |

### Phase 3 — Quality (P2) — Q4 2026

| Issue | What | Status |
|---|---|---|
| #23 | F5 benchmark harness (Simplicio × Hermes × OpenClaw) | Not started |
| #24 | F6 delivery certificate + signed ledger | Not started |
| #43 | Unified plugin system | Not started |
| #44 | Unified cron/scheduling | Not started |

### Phase 4 — Maturity (P3) — Q1 2027

| Issue | What | Status |
|---|---|---|
| #45 | Multi-profile system | Not started |
| #46 | Unified security (gate, auth, secrets) | Not started |
| #47 | Unified tests | Not started |
| #48 | Unified CI/CD | Not started |
| #49 | Unified documentation | Not started |
| #50 | Unified distribution (single binary + package managers) | Not started |
| #52 | Unified marketing | Not started |
| #54 | Unified governance | Not started |

### Turbo-speed program (F1 derivative — continuous)

| Issue | What | Status |
|---|---|---|
| #58 | Cold start: lazy imports + TTFP benchmark | Not started |
| #59 | Tool-loop: parallel execution, streaming, connection pooling | Not started |
| #60 | Hot paths: measured dispatch policy everywhere | Not started |
| #61 | Token diet: cache-sacred layout, tool-result clamping | Not started |
| #62 | Governance: permanent turbo→simplicio pipeline | Not started |

## Rules of convergence (non-negotiable)

1. **Import Hermes follows standing rule**: every new Hermes feature gets an
   issue BEFORE implementation + log in `docs/simplicio-import/`; no blind copy —
   only Simplicio-native forms (contract, skill, capability, test, adapter,
   deterministic flow, governed memory).
2. **Cache is sacred** (`system_and_3`): no convergence may break the
   prompt-cache layout; format changes are session-start-pinned.
3. **Naming**: `simplicio` (bare) = runtime Rust; Python commands end in
   `-py`; the agent resolves the kernel from PATH and never reimplements it.
4. **Guardrails yool §11 mandatory** on every new loop/fan-out
   (cpu/disk/timeout/iteration caps).
5. **ASOLARIA enters as distilled idea, not as code**: the repos are
   conceptual (JS/experiments); we import the *principle* with our own
   implementation + test + measurement, citing the source.

## Key metrics (Definition of Done for the epic)

- **Speed**: Simplicio beats Hermes Turbo in TTFT and tool-loop roundtrip
  with documented margin on the 3-agent benchmark.
- **Determinism**: zero LLM-written files in mechanical paths; every mutation
  gated; runs reproducible (versioned prompts, seeds, receipts).
- **Guarantee**: no task closes without: task anchor frozen, DoD gate green,
  delivery certificate, and watcher verdict `reported == recomputed`. Tags
  MEASURED/CANON/UNVERIFIED on every output.

## References

- Epic #18 (original F1–F6 structure)
- Issue #19 (F1: Hermes Turbo inventory)
- Issue #20 (F2: kernel binding)
- Issue #25 (this — unified roadmap)
- `docs/simplicio-import/turbo-import-matrix.md`
- `docs/architecture/ADR-0001-kernel-checkpoint-binding.md`
- `docs/architecture/ADR-0002-provider-mode-contract.md`
