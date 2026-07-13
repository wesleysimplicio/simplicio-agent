# Agent State — Estado Interno Persistente de Workers (Padrão Asolaria)

Criado em 05/07/2026. Implementa o padrão Asolaria de **agente + watcher** com
**PID persistente** e estado interno que acumula entre execuções.

## Arquitetura

```
WorkerState (PID: SUB-AGENT-PID-G1A3F-A2F-W0C8)
  ├── role: AgentRole (8 papéis: Hermes, Pi, SubAgent...)
  ├── state: AgentState (Spawned → Working → Heartbeating → Failed → Retired)
  ├── task_count, success_rate, avg_duration_ms
  ├── last_watcher_ok, watcher_failures
  └── gera NewObservation para o neural memory

Watcher (PID: SUB-AGENT-PID-G1A3F-A2F-W0C8-WATCH)
  └── watcher_verify(): output reportado == ground truth recalculado?
      → gate corretivo (padrão Asolaria N-Nest nest-depth3)
```

## Módulo

`src/asolaria/agent_state.rs` — 284 linhas, 5/5 testes passando.

### Tipos principais

```rust
pub struct WorkerState {
    pub pid: String,              // ex: "SUB-AGENT-PID-G1A3F-A2F-W0C8"
    pub watcher_pid: String,      // ex: "SUB-AGENT-PID-G1A3F-A2F-W0C8-WATCH"
    pub role: AgentRole,          // Hermes, Pi, SubAgent...
    pub state: AgentState,        // Spawned, Working, Heartbeating, Failed, Retired
    pub task_count: u64,          // tarefas recebidas
    pub success_count: u64,       // tarefas bem-sucedidas
    pub total_duration_ms: u128,  // soma dos tempos de execução
    pub last_heartbeat: u64,      // timestamp epoch
    pub created_at: u64,
    pub last_watcher_ok: bool,
    pub watcher_failures: u64,
    pub current_session: Option<SessionId>,
}
```

### Métodos principais

| Método | O que faz |
|---|---|
| `WorkerState::spawn(role)` | Cria novo worker com PID + watcher PID |
| `.success_rate()` | task_count > 0 → success_count / task_count |
| `.avg_duration_ms()` | Tempo médio por tarefa |
| `.start_working()` | State → Working, atualiza heartbeat |
| `.heartbeat()` | State → Heartbeating, atualiza timestamp |
| `.record_task(success, duration_ms)` | Incrementa contadores, atualiza heartbeat |
| `.record_watcher(ok)` | Registra veredito do watcher |
| `.to_observation()` | Gera NewObservation para neural memory |

### Watcher — Auto-reflexão com verificação independente

```rust
pub fn watcher_verify(
    worker_pid: &str,
    reported_output: &str,
    recompute_fn: impl FnOnce() -> String,
) -> WatcherVerdict {
    let expected = recompute_fn();      // watcher recalcula independentemente
    let approved = reported_output == expected;
    // gate corretivo: só passa se match
}
```

Inspirado no `nest-depth3-verify.cjs` do Asolaria (JesseBrown1980/N-Nest-Prime):
- Cada agente tem um watcher dedicado
- Watcher **recalcula** o ground truth independentemente
- Gate corretivo: pai só autoriza filho se output reportado == esperado
- Consentimento no apex: só se TODOS os níveis passarem

### PID Format

```
<ROLE-PREFIX>-PID-<REGION><COUNTER>-A<2hex>-W<3hex>
ex: SUB-AGENT-PID-G1A3F-A2F-W0C8
    PI-PID-G2B4F-A1F-W1A3
```

- `REGION`: G (Grand), H (Host), F (Federation), D (Data)
- `COUNTER`: 4 hex digits (timestamp-derived)
- `A`: activity tag (2 hex)
- `W`: wave tag (3 hex)

### Integração com ecossistema existente

```
agent_class.rs → AgentRole, AgentState  (tipos base)
pid.rs          → PID minting format     (formato Asolaria canônico)
observation.rs  → NewObservation, ObservationKind  (eventos)
store_ops.rs    → persistência SQLite    (TODO: implementar)
```

### Testes

```bash
cargo test --lib asolaria::agent_state
# 5/5: spawn, record_tasks, heartbeat, watcher_catch, watcher_approve
```

### CLI — agent-persist (implementado 05/07/2026)

Comandos disponíveis via `simplicio agent-persist` (ou `simplicio agent-state`):

```bash
# Spawnar worker com PID persistente
simplicio agent-persist spawn --role sub-agent
# 🧬 Spawned agent SUB-AGENT-PID-G79AD-AC9-W601
#    watcher: SUB-AGENT-PID-G79AD-AC9-W601-WATCH
#    (persisted to SQLite)

# Listar workers
simplicio agent-persist list
# 📋 Agents (2):
#   1. HERMES-PID-G7C44-A74-W5D4 [Hermes] — 0 tasks
#   2. SUB-AGENT-PID-G79AD-AC9-W601 [SubAgent] — 0 tasks

# Ver estado de um worker
simplicio agent-persist status --pid <PID>
# 📊 Agent: HERMES-PID-G7C44-A74-W5D4
#    watcher:  HERMES-PID-G7C44-A74-W5D4-WATCH
#    tasks:    0 (0 ok)

# Executar watcher verification manual
simplicio agent-persist watcher <PID> --reported <output>
# ✅ Watcher approved — output matches expected
# ❌ Watcher rejected: watcher mismatch: reported != expected

# Registrar tarefa + watcher automático
simplicio agent-persist record-task <PID> --success true --duration 1500 --output "task_completed"
# ✅ Task recorded for <PID>
#    success=true duration=1500ms
#    watcher: ✅ approved
# ⚠️  Task recorded for <PID> — WATCHER REJECTED
#    success=true duration=1500ms
#    watcher: ❌ watcher mismatch: reported != expected
```

### SQLite Persistence (implementado 05/07/2026)

Tabela `agent_workers` no neural memory SQLite (`~/.simplicio/memory/simplicio-memory.sqlite`):

```sql
CREATE TABLE IF NOT EXISTS agent_workers (
    pid TEXT PRIMARY KEY,
    watcher_pid TEXT NOT NULL,
    role TEXT NOT NULL,
    state TEXT NOT NULL,
    task_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    total_duration_ms INTEGER DEFAULT 0,
    last_heartbeat INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    last_watcher_ok INTEGER DEFAULT 1,
    watcher_failures INTEGER DEFAULT 0
);
```

### Integração com SelfObserver (implementado 05/07/2026)

O `self-observer.sh` (v2) agora:
1. **ensure_worker()** — spawna worker se não existir
2. Cada check registra `record-task` no worker
3. `record-task` executa watcher verification automaticamente
4. Estado persiste entre execuções do cron

```bash
# self-observer v2: workflow completo
ensure_worker                          # cria PID se necessário
check_build → cargo check             # registra record-task com resultado
check_doctor → doctor --repair        # registra record-task se reparou
$SIMPLICIO_BIN agent-persist record-task $WORKER_PID \
    --success true/false \
    --duration <ms> \
    --output "$SUMMARY"
```

### Armadilhas de implementação da CLI

1. **Subcommand parsing:** `args.first()` (não `args.get(1)`) — o dispatch já consumiu o comando raiz, então `args[0]` é o subcomando.
2. **Module resolution:** Handler na `lib.rs` → dispatch em `commands/mod.rs` (main) → usar `simplicio_runtime::modulo::funcao()`.
3. **SHA overwrite:** Múltiplos `simplicio edit --plan` no mesmo arquivo perdem alterações anteriores. Agrupar operações num único plano ou verificar SHA antes de cada replace.
4. **Build release:** demora ~10min. Usar `background=true` + `notify_on_complete=true` e continuar trabalhando.
5. **`&str` vs `String`:** `args.get(i + 1).unwrap_or("")` falha — `.map(|s| s.as_str()).unwrap_or("")` é o correto.

### Código fonte

| Módulo | Path | Linhas |
|---|---|---|
| WorkerState | `src/asolaria/agent_state.rs` | 284 (5/5 testes) |
| CLI handler | `src/agent_state_command.rs` | ~310 |
| Rota no dispatch | `src/commands/mod.rs` | 2 linhas |
| SelfObserver v2 | `~/.simplicio_agent/scripts/self-observer.sh` | ~160 |
