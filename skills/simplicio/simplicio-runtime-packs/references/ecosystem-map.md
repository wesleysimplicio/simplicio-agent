# Simplicio Runtime — Mapa do Ecossistema (16 Crates)

Schema: `simplicio.ecosystem-map/v1` · Atualizado: 03/07/2026

## Visão Geral

O runtime Rust tem **16 crates internos** + integração com **6 externos**. Cada crate expõe funcionalidades específicas que o Simplicio Agent usa via CLI ou MCP.

## Os 16 Crates Internos

| Crate | Nome real | O que faz | Como usar |
|---|---|---|---|
| **Tokyo** | `simplicio-tokill` | RTK hook system. Filtros de output, compressão. Verbosity (Lite/Full/Ultra/Wenyan). `estimate_tokens()`. Hook para auto-wrapping commands. | `simplicio shell --compact` |
| **HBI** | `simplicio-addressing` | Brown-Hilbert `port.port.port` addressing. Endereçamento de árvore hierárquica (`R.0.1.2`). Port notation. Absorvido do Asolaria. | Usado internamente para roteamento |
| **HBP** | `simplicio-fabric` | Hermes Bus Protocol. AI-native M2M fabric bus. Omnicoder (8-byte host process). FabricBus + FabricNode + packets(PacketKind) + Router. Agents comunicam via HBP, nunca chamadas diretas. | `simplicio fabric status` |
| **Agents** | `simplicio-agents` | Pool de agents + delegação + IPC + colaboração + broadcast + identidade + packet routing + bootstrap + runtime helpers + bounded ops(1536) | `simplicio agents delegate/status` |
| **Gate** | `simplicio-gate` | N-Nest corrective gate (Asolaria). Cada nó tem agent PID + watcher PID. Watcher re-computa verdade e compara. Gate + nest + verify + watcher. | `simplicio gate check` |
| **Savings** | `simplicio-savings` | Token savings ledger com hash-chain. Upgrade command. prove-real analytics. Tokenizer policy. 3 proof kinds (measured/estimated/benchmark). | `simplicio savings report/record/prove` |
| **Claims** | `simplicio-claims` | Regras de claims. Validação de tags MEASURED/UNVERIFIED. | `simplicio claims check` |
| **Security** | `simplicio-security` | Ed25519 crypto. Audit trail. Security gate. | `simplicio license status` / `security scan` |
| **GNN** | `simplicio-gnn` | Graph Neural Network. GULP pipeline (GULP trio). Hookwall. Shannon civilization. Whiteroom. | Integração com sistema de agentes |
| **Compression** | `simplicio-compression` | BEHCS-256 (8-bit, 256 symbols), BEHCS-1024 (10-bit), HyperBEHCS (variable-bit). 50+ símbolos builtin (agent, user, system, tool, etc.). 691 linhas de Rust. | `simplicio compress` |
| **Addressing** | `simplicio-addressing` | Brown-Hilbert tree addressing. Port notation. | Roteamento interno |
| **Edit** | `simplicio-edit` | Edição determinística (zero LLM tokens). Plan-based. | `simplicio edit --plan <plan.json>` |
| **Core** | `simplicio-core` | Core types, runtime map, capabilities list. | `simplicio runtime map` / `capabilities list` |
| **Harness** | `simplicio-harness` | Test harness para o runtime. | Testes internos |
| **Media** | `simplicio-media` | Media handling (áudio, imagem). | `simplicio media` |
| **Tests** | `simplicio-tests` | Test utilities. | Testes internos |
| **Gateway** | `simplicio-gateway` | API gateway. Providers config. | `simplicio proxy` |

## Crates Externos Usados

| Crate | Uso |
|---|---|
| `simplicio_cli` | CLI commands (74 comandos) |
| `simplicio_do` | Executor (run tasks) |
| `simplicio_run` | Runner (executa workflows) |
| `simplicio_core` | Core types compartilhados |
| `simplicio_agents` | Agent pool externo |
| `simplicio_savings` | Ledger de savings |

## Arquitetura de Componentes Asolaria

```
HBI (addressing) ───→ HBP (fabric bus) ───→ Omnicoder (8-byte host)
     │                       │
     ▼                       ▼
BEHCS-256/1024/Hyper    N-Nest Gate (verify)
  (compression)           (agent PID + watcher PID)
     │                       │
     └─────── GULP pipeline (GNN) ───────→ Shannon civilization
```

## 74 CLI Commands

| Grupo | Comandos |
|---|---|
| Agent Ops | agents delegate/status, sprint, governor, parallelism, plan, run, decide, task, intake |
| Issue | issue-factory (9 subcomandos), issue-worktree, pr, precedent |
| Savings | savings (9 subcomandos), benchmark, compact |
| Evidence | evidence, trajectory, learn |
| Workflow | workflow (13 subcomandos), exec-graph, cron |
| Intelligence | runtime map, memory, memory-db, memory-v2, skill-memory, orientation, invoke, advise |
| Browser | browser (10 subcomandos), computer-use |
| Connectors | telegram, discord, login, license, proxy |
| Utils | backup, cache, completion, hooks, install, packages, pairing, recover, security, setup, update, version, welcome, shell, status, toolchain, model, chat, contracts, doctor |

## Limitações Conhecidas

- `simplicio agents delegate` completa instantaneamente sem executar multi-step real
- `delegate_task` com `acp_command="claude"` falha (Claude Code 2.1.198 não suporta --acp)
- Build release Rust leva 10-15min
- Main protegido no GitHub — sempre via PR
- Python 3.9 do sistema não atende pacotes que exigem >=3.10
