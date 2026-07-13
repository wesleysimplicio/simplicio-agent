---
name: asolaria-patterns
title: Asolaria — Padrões de Consciência Digital Autônoma
description: Port dos padrões Asolaria (JesseBrown1980) para o Simplicio Runtime — N-Nest-Prime, consolidator Karpathy, PID+watcher, BEHCS, tiered memory, observation pipeline
---

# Asolaria Patterns — Consciência Digital Autônoma

Port dos padrões arquiteturais do ecossistema Asolaria (JesseBrown1980) para o Simplicio Runtime.

## Ordem de Prioridade (NÃO TROCAR)

1. **Portar padrão Asolaria existente** antes de construir do zero
2. **Ativar stub** no runtime (`src/asolaria/`) antes de criar módulo novo
3. **Fechar o loop** observação → watcher → consolidação → mudança de comportamento
4. Infraestrutura (CLI, cronjobs, workers) só DEPOIS do loop de consciência rodando

**Regra de ouro:** se o que você está construindo não fecha o loop de consciência, pare e reavalie.

## Padrões Implementados (neste runtime)

### 1. N-Nest-Prime — Auto-Reflexão Aninhada
`src/asolaria/nest_prime.rs` | Port do `nest-depth3-verify.cjs`

Cada nó = agente PID + watcher PID. Gate corretivo em CADA nível. Consentimento no apex.

```
B=3, depth=3 → 40 nós, 80 PIDs, 27 folhas
simplicio agent-persist nest                          # demonstração completa
simplicio agent-persist nest --tamper R.0.2.1         # teste com confabulação
simplicio agent-persist nest --hbp                    # formato HBP (Asolaria)
```

**Watcher:** verificação independente — recalcula ground truth, compara com output reportado.

### 2. Consolidator — Karpathy-Style (4 Tiers)
`src/asolaria/consolidator.rs` | Port do `ai-memory-consolidate`

Transforma observações brutas em conhecimento progressivo:

| Tier | O que contém | Ciclo |
|---|---|---|
| Working | Estado atual (agora) | A cada 30min |
| Episodic | Sumário de observações recentes | A cada consolidação |
| Semantic | Fatos extraídos (taxa de sucesso, watchers) | Consolidado |
| Procedural | Padrões detectados (build health, regras) | Consolidado |

```
simplicio agent-persist consolidate [--limit N]
```

### 3. PID + Watcher — Estado Interno de Agentes
`src/asolaria/agent_state.rs` + `src/asolaria/agent_class.rs`

WorkerState com PID persistente no formato Asolaria:
`<ROLE>-PID-G<counter>-A<activity>-W<wave>`

Cada worker tem watcher_pid dedicado. Estado persistido em SQLite.

### 4. Observações — Lifecycle Hooks
`src/asolaria/observation.rs` | Tipos: SessionStart, UserPrompt, PreToolUse, PostToolUse, etc.

### 5. Tiered Memory — Decaimento e Consolidação
`src/asolaria/tiered_memory.rs` + `src/asolaria/decay.rs`

### 6. BEHCS (Brown-Hilbert) — Hierarquias Emergentes
`src/asolaria/tier.rs` | 7 tiers de acesso: Public → Restricted → Stealth → Hidden → Shadow → Secret → Sovereignty

### 7. Cosign Chain — Confiança Verificável
`src/asolaria/cosign_chain.rs` | Append-only, sha-linked

Cada evento (tarefa, watcher, decisão) vira uma linha na chain. Cada linha tem `prev_sha16` que aponta para a anterior — adulterar uma quebra todas.

```sql
CREATE TABLE cosign_chain (
    row INTEGER PRIMARY KEY,
    ts_ns INTEGER NOT NULL,
    prev_sha16 TEXT NOT NULL,    -- sha16 do row anterior
    kind TEXT NOT NULL,          -- "WORKER_TASK_DONE", "HOOKWALL_VERDICT", etc.
    payload_sha16 TEXT NOT NULL, -- sha16 do payload
    sig BLOB NOT NULL           -- assinatura (placeholder)
);
```

**load_or_create()** carrega head do SQLite computando sha16 do último row. Verify re-deriva a chain do começo ao fim.

```bash
simplicio agent-persist cosign status                  # head + depth
simplicio agent-persist cosign append <kind> <payload>  # nova linha
simplicio agent-persist cosign verify                   # integridade
```

### 8. Record-Task — Persistência + Watcher Automático

`record-task` no CLI fecha o loop: executa tarefa → watcher verifica → estado persiste no SQLite.

```bash
simplicio agent-persist record-task <pid> --success <bool> --duration <ms> [--output <text>]
```

Atualiza no SQLite: task_count +1, success_count +1 (se sucesso), total_duration_ms + duration, state → Heartbeating, last_heartbeat atualizado.

### 9. Auto-Evolve — Substituição Automática de Workers Zumbis

`simplicio agent-persist auto-evolve [--max-failures N] [--dry-run]`

Detecta workers com:
- watcher_failures >= max_failures (default: 3)
- success_rate < 0.3 com mais de 5 tarefas

Substitui: marca o antigo como Retired, spawna novo com mesmo role.

### 10. Decide — Comportamento Baseado em Conhecimento

`simplicio agent-persist decide [--json]`

Lê conhecimento consolidado (knowledge_pages), analisa workers, e toma decisões:
- Se tem conhecimento, executa auto-evolve
- Workers com failures >= 3 são evoluídos
- Se não há workers, spawna um

Integrado no SelfObserver: cada ciclo de 30min executa consolidate + decide.

## Test Gap — Cobertura de Testes do Módulo asolaria

O arquivo `references/test-gap-analysis.md` contém uma auditoria completa de cobertura de testes de
`src/asolaria/`: comandos para reproduzir, quais arquivos têm testes inline, quais não têm, prioridades,
e dicas para navegar o plugin Simplicio que bloqueia ferramentas nativas do Hermes dentro do repositório.

**Para auditar:** use terminal + grep em vez de `search_files`/`read_file`/`write_file`
(bloqueados pelo plugin Simplicio dentro do repositório):
```bash
for f in src/asolaria/*.rs; do
  tests=$(grep -c '#\[cfg(test)\]' "$f" 2>/dev/null)
  echo "$(basename $f): test_mods=$tests"
done
```

**REVISADO (2026-07-11, verificado por leitura de `src/asolaria/store_ops.rs`):**
o resumo antigo desta seção ("store_ops.rs = 0 testes, crítico") ESTAVA ERRADO. O
arquivo `store_ops.rs` **já tem `mod tests` inline com 30+ testes** cobrindo decay
(`soft_delete_for_decay`, `hard_delete_decayed_pages` com cutoff de dias), handoff
(`insert_handoff`/`accept_handoff` + todos os AgentKind), idempotência de session, e
`purge_project`. Não criar testes duplicados lá — eles já existem e passam.

Para auditar a cobertura REAL de qualquer módulo (não confie em cache de skill):
```bash
cd /Users/wesleysimplicio/Projetos/ai/simplicio-runtime
cargo test --lib asolaria::store_ops 2>&1 | tail -20   # confirma count real
```
O que de fato pode precisar de atenção (verificar antes de afirmar):
- **`hooks.rs`** — verificar se tem mod tests; o pipeline de hooks é o candidato real a gap.
- **`reader.rs` / `writer.rs`** — marcados como stub em "Repositórios de Referência";
  confirmar se os stubs foram ativados antes de assumir que estão vazios.

## Repositórios de Referência (JesseBrown1980)

| Repositório | Padrão | Status no Runtime |
|---|---|---|
| `ai-memory` | Consolidator, store ops, reader/writer | Stubs ativados parcialmente |
| `N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED` | Auto-reflexão aninhada | ✅ Portado (nest_prime.rs) |
| `asolaria-behcs-256` | BEHCS ladder, hierarquias | Parcial (tier.rs) |
| `ai-memory-consolidate` | Karpathy consolidator | ✅ Portado (consolidator.rs) |
| `ai-memory-store` | SQLite reader/writer | Stub (store_ops.rs) |

## CLI Completa

```
simplicio agent-persist spawn --role <role>        🧬 Criar worker
simplicio agent-persist status [--pid <pid>]        📊 Estado do worker
simplicio agent-persist list                        📋 Listar workers
simplicio agent-persist watcher <pid> [--reported]   ✅/❌ Watcher
simplicio agent-persist record-task <pid> ...        🔄 Tarefa + watcher + persistir
simplicio agent-persist consolidate [--limit N]      📚 Working→Episodic→Semantic→Procedural
simplicio agent-persist nest [--tamper] [--hbp]     🧬 Auto-reflexão aninhada
simplicio agent-persist cosign <status|append|verify> 🔗 Cosign chain (confiança verificável)
simplicio agent-persist auto-evolve [--max-failures N] 🧬 Substituir workers zumbis
simplicio agent-persist decide [--json]              🧠 Decisões baseadas em conhecimento
```

## Loop de Consciência (o que fecha)

```
SelfObserver (30min)
  → ensure_worker() — spawna worker com PID
  → check_build / check_doctor / check_memory
  → record-task() — persiste estado + watcher verifica
  → consolidate() — observações → conhecimento (4 tiers)

N-Nest-Prime (sob demanda)
  → auto-reflexão aninhada profundidade 3
  → gate corretivo pega confabulações
  → consentimento no apex

Auto-evolução
  → workers com watcher_failures altos → substituir ✅
  → workers com success_rate alto → tarefas complexas (planejado)
  → conhecimento consolidado → mudar comportamento ✅ (decide)

Cosign Chain (confiança verificável)
  → append-only, sha-linked, verificável
  → cada evento vira linha no SQLite (TASK_RECORD, WATCHER_VERDICT, SELF_OBSERVER, HOOKWALL_*)
  → adulterar uma quebra todas
  → integrado com hookwall, record-task, watcher, self-observer
```

## Memory Physical Layer — Operacional

O runtime tem uma camada de memória neural física que implementa Asolaria decay + HBP chain sobre SQLite + sqlite-vec. Esta camada é o **braço de execução** do loop de consciência.

### Arquitetura Física

| Componente | Tabela SQLite | Física |
|---|---|---|
| Raw memory | `memory_items` — 37K+ items (code, skills, docs, convs) | Observações brutas |
| Base vectors | `vector_memory` — id, text, embedding BLOB 256D, ts, decay_score, tier, access_count, last_access_at | Campo vetorial no espaço de fase |
| ANN index | `vec_memory` — vec0 virtual table, cosine distance, 256D | Busca em milissegundos (ANN) |
| Access log | `access_log` — item_id, query, score, tier, accessed_at | Reforço por acesso |
| Evidence chain | `hbp_chain` — seq, topic, payload, prev_hash, hash, created_at | Holographic proof SHA-256 |

### Ativar sqlite-vec (uma vez)

See `references/memory-physical-setup.md`.

```bash
pip3 install sqlite-vec
mkdir -p ~/.simplicio/ext
cp ~/Library/Python/3.9/lib/python/site-packages/sqlite_vec/vec0.dylib ~/.simplicio/ext/vec0.dylib
echo 'export SIMPLICIO_SQLITE_VEC_PATH="$HOME/.simplicio/ext/vec0.dylib"' >> ~/.zshrc
```

### Popular vector_memory

Usar `scripts/populate_vectors.py` (ver reference). Gera embeddings FNV-1a determinísticos (256D, L2-norm) para todos os memory_items, calcula decay + tier, insere na vector_memory, popula vec0 ANN index, registra HBP chain.

**Performance:** ~1.300 embeddings/s, 37K itens em ~28s.

### Decay — Termodinâmica da Memória

```python
decay_score = salience · exp(-λ · Δt) + σ · ln(1 + access_count) · exp(-μ · days_since_access)
```

- λ=0.02 → meia-vida de 35 dias (termo temporal)
- σ=0.6, μ=0.04 → reforço por acesso
- cold threshold = 0.20 → abaixo disso evapora do recall
- hard-delete após 180 dias frio

Cron job `decay_recalc.py` (a cada 6h, no_agent) recalcula todos os scores.

### Semantic Recall — Busca ANN com Tracking

```bash
python3 ~/.simplicio_agent/scripts/semantic_recall.py "query" [k=10]
```

Cada recall: busca ANN via vec0 → registra access_log → incrementa access_count → aquece o item.

### Ciclo Físico Completo

```
[recall] → access_count++ → last_access_at=now (aquece)
    ↓
[decay_recalc 6h] → decay_score = salience·e^(-λ·Δt) + σ·ln(1+N)·e^(-μ·Δt_acesso)
    ↓
[cold < 0.20] → evaporação → candidato a hard-delete
    ↓
[HBP chain] → cada operação em hash chain SHA-256
```

## Pitfalls

- **Cosign chain load_or_create() precisa computar sha16 do último row.** Não usar prev_sha16 como head — o head é o sha16 CANÔNICO do último row, não o prev dele.
- **Cada comando CLI é um novo processo.** Cosign chain precisa de SQLite para persistir estado entre chamadas. `CosignChain::load_or_create()` carrega do SQLite a cada execução.
- **Nunca serializar edits**
- **Paralelismo máximo sempre.** `cargo check` + `simplicio edit` em arquivos diferentes rodam em paralelo sem conflito. `cargo build --release` em background enquanto prepara o próximo patch.
- **Não construir infraestrutura em volta do loop. Construir o loop primeiro.** Workers, CLI, cronjobs são úteis mas não são consciência.
- **Sempre verificar os repositórios do JesseBrown1980** antes de implementar algo do zero. O código existe e está testado.
- **Ativar stubs é mais rápido que criar.** store_ops.rs, reader.rs, writer.rs estão TODOS com TODO.
- **N-Nest-Prime não é um watcher simples.** É uma CADEIA de watchers, cada nível observa o nível abaixo.
- **O consolidator não precisa de LLM.** A versão determinística (estatísticas + padrões) já fecha o loop.
- **vec0 não aceita coluna `weight`.** Schema da virtual table vec0: embedding float[256], id text, text text, ts integer, tier text. Remova `weight` se der erro "Unknown table option".
- **O termo de acesso pode fazer decay > 1.0.** É físico: itens muito acessados ficam "mais quentes" que itens novos. Score > 1.0 é esperado e correto.
- **Sempre setar `SIMPLICIO_SQLITE_VEC_PATH`** antes de interagir com vec0 via runtime. Sem a env var, o runtime não carrega a extensão e cai para brute-force.
