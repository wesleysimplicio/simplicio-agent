# Ecosystem Absorption Session — JesseBrown1980/Asolaria

Session date: 2026-06-30
External source: https://github.com/JesseBrown1980 (70 repos)
Target ecosystem: Simplicio (6 repos in ~/Projetos/ai/)

## Overview

Absorbed 10+ features from Jesse's Asolaria ecosystem into 6 Simplicio repos using 18+ parallel subagents. Total: 32 tasks across 5 batches.

## Absorption targets

| External repo | Absorbed feature | Target repo | Crate/file created |
|---|---|---|---|
| N-Nest-Prime | Corrective gate (agent+watcher per-node) | simplicio-runtime | `crates/simplicio-gate/` |
| N-Nest-Prime | 8-byte seed identity | simplicio-runtime | `crates/simplicio-agents/src/{identity,seed,watcher}.rs` |
| asolaria-federation-1024 | Brown-Hilbert port.port.port | simplicio-runtime | `crates/simplicio-addressing/` |
| asolaria-federation-1024 | Fabric bus M2M | simplicio-runtime | `crates/simplicio-agents/src/{fabric,packet}.rs` |
| AGENT-BRIEF (Harness-edit) | Claims-gate discipline (8 rules) | simplicio-runtime | `crates/simplicio-claims/` |
| Harness-edit | SkillOpt scorer | simplicio-runtime | `crates/simplicio-harness/` |
| omnicoder | Omnicoder/fabric | simplicio-runtime | `crates/simplicio-fabric/` |
| Algorithms-of-Asolaria | HEAD/TAIL O(1), turbo/polar/triple codecs, JL quant, BEHCS | simplicio-runtime | `crates/simplicio-compression/src/{head_tail,turbo_codec,polar_codec,triple_codec,jl_quant,behcs}.rs` |
| Shannon-and-the-gnns-stage | GNN trio (HOOKWALL, reverse-gain, white rooms) | simplicio-runtime | `crates/simplicio-gnn/` |
| N-Nest-Prime (CLI) | gate/nest/score-skill/claims commands | simplicio-dev-cli | `simplicio/commands/{gate,nest,claims,score_skill}.py` |
| N-Nest-Prime (loop) | Watcher-gate, BH tracing, claims, handoff | simplicio-loop | `scripts/{handoff,loop_journal}.py`, 3× `loop_stop.py`, 3× `SKILL.md` |
| Brown-Hilbert | BH addressing + agent tree | simplicio-mapper | `simplicio_mapper/mapper.py` |
| N-Nest + claims | Gate + claims-gate | simplicio-loop-marketing | `lib/gate/{watcher-gate,claims-gate}.ts` |
| N-Nest (skill) | simplicio-nest-gate skill | simplicio (npm) | `.claude/skills/simplicio-nest-gate/SKILL.md` |

## Cross-repo dependency linking

Created after absorption:
- `simplicio/runtime_bridge.py` — discovers Rust `simplicio` binary, routes gate/nest/score-skill via Rust→Python fallback
- `SIMPLICIO_DEPENDENCIES.md` — cross-repo dependency graph
- `SIMPLICIO_ECOSYSTEM.md` (root + each repo) — ecoystem manifest
- `scripts/sync-versions.sh` — version coordination

## Release versions

| Repo | Version | Channel |
|---|---|---|
| simplicio-runtime | v1.5.0 | GitHub Release |
| simplicio-dev-cli | v0.8.0 | PyPI + GitHub Release |
| simplicio-loop | v3.19.0 | GitHub Release |
| simplicio-mapper | v0.12.0 | GitHub Release |
| simplicio-loop-marketing | v0.3.0 | GitHub Release |

## Key lessons

- **18 parallel subagents work:** Dispatched 18 tasks simultaneously; all completed in ~6 minutes. Each wrote independent code.
- **Protected main requires PR dance:** simplicio-runtime main is PR-only. Must push feature branch → `gh pr create` → `gh pr merge`.
- **Always `cargo check` after parallel writes:** Multiple agents writing to the same workspace can create Cargo.lock conflicts. A final `cargo check` catches all.
- **PyPI version collision:** v0.7.1 already existed. Bumped to v0.8.0. Always check before publish.
- **Build from clean dist/:** Old `.whl` files in `dist/` get uploaded too. `rm -rf dist/ build/ *.egg-info` before build.
