# Simplicio — 12 Áreas de Melhoria Prioritárias

> Gerado em 2026-06-17, consolidado de análise do runtime de 277 arquivos .rs
> Runtime: monofile ~84K linhas, 290 match arms de dispatch

## Resumo

| # | Área | Prioridade | Esforço |
|---|------|-----------|---------|
| 1 | Modularizar monólito (84K+ main.rs) | 🔴 Alta | 3-4 semanas |
| 2 | Testes automatizados (zero atuais) | 🔴 Alta | 2-3 semanas |
| 3 | Agent IPC (schema 8 meses sem impl) | 🔴 Alta | 2 semanas |
| 4 | CI/CD pipeline | 🔴 Alta | 1 semana |
| 5 | Self-healing (crash, lock, deadlock) | 🔴 Alta | 1-2 semanas |
| 6 | Feature flags + canary releases | 🟡 Média | 1-2 semanas |
| 7 | Observabilidade e dashboards | 🟡 Média | 1-2 semanas |
| 8 | Loop de aprendizado contínuo | 🟡 Média | 2 semanas |
| 9 | LLM multi-provedor + roteamento | 🟡 Média | 2-3 semanas |
| 10 | Remover código morto | 🔴 Alta | 1 semana |
| 11 | Skills em markdown (Hermes parity) | 🔴 Alta | 2-3 semanas |
| 12 | Hermes parity (tools, flexibilidade) | 🟡 Média | Contínuo |

---

## 1. Modularizar Monólito

**Problema:** `main.rs` tem 84K+ linhas com 290 match arms de dispatch. Código
difícil de navegar, conflitos de merge frequentes, compilação lenta, sem
boundaries claros entre módulos.

**Ação:** Extrair em crates separadas no workspace Cargo:
- `simplicio-gateway` — 15 plataformas de comunicação
- `simplicio-edit` — edição determinística (edit, mechanical-edit)
- `simplicio-agents` — dispatch de agentes, organism, organism/ (23 módulos)
- `simplicio-security` — gates, guardians, enforcement
- `simplicio-savings` — savings report, token tracking
- `simplicio-core` — runtime map, orient, contracts

**Critérios:** Workspace 5+ crates, main.rs < 500 linhas, compilação incremental,
cada crate com cargo test próprio.

## 2. Testes Automatizados

**Problema:** Zero testes no runtime. `#![allow(dead_code)]` em 50+ módulos.
Toda refatoração é voo cego.

**Ação:**
- F1: Testes de unidade (gate, security, hooks, edit)
- F2: Testes de snapshot CLI (cada comando produz saída verificável)
- F3: Testes de integração (pipeline edit → validate)
- F4: CI integration (cargo test em todo PR)

## 3. Agent IPC

**Problema:** Schema `agent-ipc/v1` existe há 8 meses sem implementação.
23 módulos em `organism/` não têm comunicação real entre processos.

**Ação:**
1. Implementar agent-ipc via stdin/stdout JSON-RPC
2. Wirear organism/ com heartbeat, message routing por capability
3. Schemas agent-lease, agent-escalation-policy

## 4. CI/CD Pipeline

**Problema:** Gates existem mas sem pipeline automatizado. Releases manuais.

**Ação:**
1. `simplicio ci run` (lint→build→test→security→package→sign)
2. GitHub Actions: ci.yml (push/PR), release.yml (merge), nightly.yml
3. Auto-release: PR passa gates → auto-merge → bump version → GitHub Release

## 5. Self-Healing

**Problema:** SIGKILL por RAM, lock contention (`repo.lock`), agents órfãos.
Recuperação 100% manual.

**Ação:**
- `simplicio recover --auto` (limpa locks, mata agents, restaura estado)
- Health endpoint HTTP
- Watchdog systemd/LaunchAgent
- Graceful degradation (reduz agents em pico de RAM)

## 6. Feature Flags + Canary Releases

**Problema:** Todo comando é compilado direto no binário. Se quebrar, quebra tudo.

**Ação:**
1. Feature gates no Cargo.toml: stable/beta/nightly
2. `simplicio update check --channel stable|beta|nightly`
3. Kill switch: auto-rollback em crash na inicialização
4. `simplicio feature list|enable|disable`

## 7. Observabilidade

**Problema:** Sem métricas de runs, taxa de sucesso, tempo de pipeline, crashes.

**Ação:**
1. Métricas instrumentadas (contadores, timers, gauges)
2. `simplicio metrics` (dashboard terminal + export JSON/Prometheus)
3. Dashboard HTML local com chart.js
4. Crash tracking (`simplicio crash list|show`)

## 8. Loop de Aprendizado Contínuo

**Problema:** Captura de trajectories é manual. Helo só aprende quando alimentado.

**Ação:**
1. Auto-record de trajectories em toda run/edit
2. Cron noturno: meta analyze → learn apply → meta propose
3. Sugestão proativa de skills baseada em padrões repetidos

## 9. LLM Multi-Provedor

**Problema:** 5 provedores compilados, só OpenRouter wireado. SPOF.

**Ação:**
1. Roteamento inteligente: simples→local, média→barato, complexa→forte
2. Fallback automático entre provedores
3. Wirear Anthropic/DeepSeek/Gemini/Mistral (existe, não wireado)
4. Modelo local como cidadão de primeira classe

## 10. Remover Código Morto

**Problema:** ~189 `#![allow(dead_code)]`, 2 arquivos não compilados, 72KB duplicado.

**Ação:**
1. `final_modules.rs` (6.7KB) — deletar
2. `provider_command.rs` (72KB) — integrar ou deletar
3. `voice_orb.rs`, `wake_on_voice.rs` — feature gate `voice`
4. Remover `#![allow(dead_code)]` módulo por módulo

## 11. Skills em Markdown

**Problema:** Skills são Rust compilado. Criar skill = compilar 2-5 min.
No Hermes são arquivos .md sem compilação.

**Ação:**
1. Diretório `~/.simplicio/skills/` com arquivos `.skill.md` (YAML frontmatter)
2. `simplicio skill list|show|create|edit|search|import`
3. Auto-descoberta + hot-reload
4. Core em Rust, skills em markdown, scripts Python opcionais (subprocess)

## 12. Hermes Parity

**Problema:** Hermes tem vantagens em tools, flexibilidade e ecossistema.

**Gaps por fase:**

| Fase | Itens |
|------|-------|
| Crítico | Vision tool, TTS/STT, Session search FTS5, Skills markdown, Testes |
| Médio | Skills hub público, Checkpoints, Hot-reload tools, Multi-channel personas |
| Ecossistema | Contributing guide, CI/CD, Skills catalog comunitário, Docs completas |

**Arquitetura:** "Rust é motor central, camadas externas em Python/markdown."

---

## Scripts Relacionados

Os scripts `create-issue-*.sh` em `~/.hermes/skills/fix-enforcement/scripts/`
contêm os bodies completos de cada issue para recriação no GitHub.
O script `run-all-issues.sh` executa todos em sequência.

Uso:
```bash
bash ~/.hermes/skills/fix-enforcement/scripts/run-all-issues.sh <repo-slug>
```
