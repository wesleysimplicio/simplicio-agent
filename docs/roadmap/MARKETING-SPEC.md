# Unified Marketing — Specification

> **Issue:** #52 — [P3] Marketing Unificado
> **Spec version:** 1.0 (2026-07-03)

## Objective

Unify the narrative and marketing collateral for the Simplicio Agent:
"Simplicio on Metal" — single binary, no cloud, open-core agent for
developers who want speed, determinism, and guarantee by construction.

## Core narrative

**Simplicio Agent = The fastest, most deterministic, most guaranteed agent
you can run on your own machine.**

Three pillars:
1. **Speed** (Hermes Turbo DNA): measured, benchmarked, faster than Hermes
   and OpenClaw in TTFT and tool-loop roundtrip.
2. **Determinism** (Simplicio Runtime): zero-LLM edits, action-gated
   mutations, checkpoints, tamper-evident ledger. No surprises.
3. **Guarantee** (ASOLARIA principles): every output tagged
   MEASURED/CANON/UNVERIFIED. Watcher-gate recomputes results. Delivery
   certificates for every task.

## Target audiences

1. **AI engineers / agent builders** — want a controllable, auditable agent
   they can ship to production without "black box" risk.
2. **OSS developers** — want the fastest local agent for coding tasks,
   CLI-native, no Electron overhead.
3. **Enterprises** — want deterministic, auditable agent behavior with
   signed delivery certificates for compliance.

## Deliverables

### Phase 1 — Foundation

- [ ] **Landing page** at simpleti.com.br unified — "Simplicio on Metal: The
  Agent That Runs on Your Hardware"
- [ ] **`README.md`** updated with the three-pillar narrative (currently has
  Hermes-era messaging)
- [ ] **`REDUCTIONS.md`** — catalog of token/cost savings per feature
  (mechanical edit, TOON compression, action gate, watcher recompute)

### Phase 2 — Collateral

- [ ] **Case study**: "Task X — before vs after" showing token savings,
  wall-clock improvement, and determinism guarantees
- [ ] **Benchmark page**: published 3-agent comparison (Simplicio × Hermes ×
  OpenClaw), refreshed per release
- [ ] **Screenshots/gifs**: CLI demo, TUI, MCP integration

### Phase 3 — Community

- [ ] **Discord #showcase**: template for community benchmarks
- [ ] **Twitter/X thread**: launch announcement with benchmark numbers
- [ ] **Blog post**: "Why determinism matters for AI agents"

## Messaging rules

1. **Numbers everywhere**: every claim backed by a benchmark or measurement.
   No "faster" without "X% faster on Y benchmark with Z methodology."
2. **Open-core positioning**: core agent is MIT; enterprise features
   (licensing, PyArmor, Nuitka binary) are commercial.
3. **"Simplicio on Metal"** is the tagline — emphasis on local-first,
   user-owned hardware.

## References

- Issue #52 (this spec)
- `docs/performance.md` — benchmark data
- `docs/roadmap/SIMPLICIO-ROADMAP.md` — strategic context
