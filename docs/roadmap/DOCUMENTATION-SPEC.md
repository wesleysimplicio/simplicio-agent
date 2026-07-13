# Documentation Unification — Specification

> **Issue:** #49 — [P3] Unificacao de Documentacao
> **Spec version:** 1.0 (2026-07-03)

## Objective

Unify all documentation artifacts across the Simplicio Agent ecosystem into
a single, coherent documentation surface — one AGENTS.md, one SKILL.md per
skill, consistent architecture docs, and multi-language READMEs.

## Current state

Simplicio Agent inherited the full Hermes Agent documentation surface
(~200+ files in `archive/website/docs/`) plus its own growing set of docs
in `docs/`. The website documentation is archived (`archive/website/`), but
the agent-specific docs are scattered.

### What exists in `docs/` (agent-specific)

| File | Purpose |
|---|---|
| `docs/ASOLARIA_ABSORPTION_PLAN.md` | ASOLARIA principles absorption plan |
| `docs/SYNC_PIPELINE.md` | Ecosystem sync pipeline (Hermes → Turbo → Simplicio) |
| `docs/TOON-CONTRACT.md` | TOON codec specification |
| `docs/performance.md` | Performance benchmark documentation |
| `docs/session-lifecycle.md` | Session lifecycle |
| `docs/relay-connector-contract.md` | Relay connector contract |
| `docs/mcp-telemetry.md` | MCP telemetry instrumentation |
| `docs/middleware/README.md` | Middleware system |
| `docs/observability/README.md` | Observability stack |
| `docs/security/network-egress-isolation.md` | Network egress isolation |
| `docs/design/profile-builder.md` | Profile builder design |
| `docs/kanban/multi-gateway.md` | Multi-gateway kanban |
| `docs/architecture/ADR-0001*.md` | ADR: kernel checkpoint binding |
| `docs/architecture/ADR-0002*.md` | ADR: provider-mode contract |
| `docs/simplicio-import/` | Hermes Turbo import artifacts (matrix + log) |
| `docs/roadmap/` | Roadmap and planning |

## Deliverables

### Phase 1 — Structure (P3a)

- [ ] **`docs/README.md`** — top-level docs index linking to every doc
- [ ] **`docs/architecture/README.md`** — architecture doc index
- [ ] Directory tree cleanup: move standalone docs into subdirectories

### Phase 2 — Consolidation (P3b)

- [ ] **Merge `AGENTS.md`** with Hermes upstream's contribution model
  (Simplicio-specific overrides noted as deltas)
- [ ] **`SKILL.md` per bundled skill** (skills under `skills/`)
- [ ] **`ARCHITECTURE.md`** — single architecture overview from bootstrap to tool loop
- [ ] **Multi-language READMEs**: keep pt-BR, es, zh-CN, ur-PK alive and in sync

### Phase 3 — Automation (P3c)

- [ ] Doc lint: `scripts/check.py docs` — verify links are valid, no broken cross-refs
- [ ] Release checklist includes doc generation step
- [ ] Pre-commit hook: `ruff` for docs code blocks

## Naming conventions

- `docs/` for agent-specific documentation (what the agent does, how it's built)
- `skills/<name>/SKILL.md` for skill documentation (what the skill does, examples)
- `docs/architecture/` for Architectural Decision Records and structural docs
- `docs/roadmap/` for planning and roadmap documents

## References

- Simplicio Agent docs structure
- Hermes upstream docs at `archive/website/docs/`
- Issue #49 (this spec)
