# Release v1.0.5 — Source adapters + Accelerators

**Date:** 2026-06-23
**Repo:** wesleysimplicio/simplicio-loop (Python super-plugin)
**Version files:** `.claude-plugin/plugin.json`, `.cursor-plugin/plugin.json`, `pyproject.toml`

## Changes

### New source adapters
- **agentsview** (kenn-io) — session analytics, cost observability, stalled session recovery
  - `scripts/agentsview_adapter.py` — CLI com 8 verbs (list_ready, get_details, claim, update_status, attach_evidence, close, cost_summary, agent_breakdown)
  - Modos SQLite direto (recomendado) + HTTP API
  - `references/agentsview-adapter.md` — 210-line contract

### New accelerators
- **Understand Anything** (Egonex-AI) — knowledge-graph code orientation via `orient` extension point
  - 591-line reference doc com schema jq queries guided tours
  - L0 (zero tokens) — consultas JSON, não LLM
- **LMCache** — KV cache inference accelerator
  - 632-line reference doc com instalação, config MP architecture
  - 40-70% redução de TTFT em modelos locais (L2-L3)

### Fluxo atualizado
- Step 1a: agentsview cost check no pre-flight budget
- Step 2b-2: Understand Anything como orientação primária
- Step 3b: agentsview como fonte opcional no poller contínuo
- Step 3d: LMCache como acelerador de inferência local
- extension-points.md: orient + model_route atualizados
- token-economy.md: seção LMCache

### README
- Seções novas: Source Adapters, Accelerators, Recent Activity, Design Pillars
- Badges: 6 source adapters, 3 accelerators, 43 extension points
- Últimos 10 PRs listados (22→39)

### Fixes applied during review
- UA removido da tabela de source adapters (não é fonte de work-items)
- Itálico → blockquote nas anotações de fluxo (agentsview Step 3b, UA Step 2b-2)
- Numbering corrigida no SKILL.md Step 1a (1b. → sub-bullet)
- L4 pipe extra removido (||-**L4** → |-**L4**)

## Published channels

| Channel | Status | Detail |
|---------|--------|--------|
| GitHub Release | ✅ Latest | v1.0.5 |
| GitHub tag | ✅ | main + v1.0.5 |
| PyPI | ✅ | simplicio-loop 1.0.5 |

## Key correction from this session

**Use the simplicio-loop protocol for ALL implementation work.** Do not jump to
write_file/patch directly. Steps: preflight → survey (simplicio-mapper) → triage →
decide → operate (simplicio-dev-cli task) → verify → promise (evidence-gated).

**Also:** UA é ferramenta de orientação, não fonte de work-items — não colocar na
tabela de source adapters.
