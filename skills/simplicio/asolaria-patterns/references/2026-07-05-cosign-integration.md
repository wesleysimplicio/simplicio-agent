# Cosign Chain Integration — 2026-07-05

## O que foi implementado

### Cosign chain integrada com record-task e watcher

Cada `record-task` agora:
1. Atualiza worker state no SQLite (task_count +1, etc.)
2. Gera linha na cosign chain: `WORKER_TASK_RECORD` com pid + success + duration
3. Executa watcher verification
4. Gera linha na cosign chain: `WATCHER_VERDICT` com approved + reason

### SelfObserver v2 — ciclo completo

```
self-observer.sh (cada 30min)
  → ensure_worker() — spawna worker com PID se não existir
  → check_build() — cargo check + auto-fix
  → check_doctor() — simplicio doctor --repair
  → check_trajectories / check_memory / check_last_build
  → cosign append (SELF_OBSERVER + summary)
  → SQLite observation (memory_items, kind='observation')
  → memory-v2 store (fallback)
  → record-task (persiste + watcher verifica)
  → consolidate (4 tiers: Working→Episodic→Semantic→Procedural)
  → decide (ações baseadas em conhecimento)
```

### Comandos novos

```bash
simplicio agent-persist cosign status              # head + depth
simplicio agent-persist cosign append <kind> <pay>  # append row
simplicio agent-persist cosign verify               # integridade
simplicio agent-persist consolidate [--limit N]      # 4 tiers
simplicio agent-persist decide [--json]              # ações
simplicio agent-persist auto-evolve [--dry-run]      # substituir zumbis
```

## Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `src/agent_state_command.rs` | record-task + watcher → cosign append. Comandos cosign, consolidate, decide, auto-evolve |
| `src/asolaria/cosign_chain.rs` | load_or_create com head real (sha16 do último row, não prev_sha16). Testes 8/8 |
| `src/asolaria/hookwall.rs` | Usa CosignChain::load_or_create() em vez de append() livre |
| `~/.simplicio_agent/scripts/self-observer.sh` | Ciclo completo: cosign → SQLite → record → consolidate → decide |

## Testes

- `asolaria::cosign_chain`: 8/8 passando
- `asolaria::nest_prime`: 6/6 passando
- `asolaria::consolidator`: 6/6 passando
- Build: 0 erros (debug + release)

## Lições

- `load_or_create()` precisa computar sha16 do último row, não usar prev_sha16
- Cada chamada CLI é um novo processo → cosign chain precisa de SQLite para persisti
- `cargo build` (debug, 1-2min) é suficiente para testes. Release só no final
