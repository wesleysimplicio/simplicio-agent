# Asolaria N-Nest Depth-3 — Padrão de Auto-Reflexão com Gate Corretivo

Decodificado do repositório `JesseBrown1980/N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED` (05/07/2026).
Arquivo-fonte: `nest-depth3-verify.cjs` — verificador empírico do padrão de auto-reflexão aninhada.

## O Padrão

Cada nó (agente) tem **dois PIDs**:
1. **Agent PID** — executa o trabalho
2. **Watcher PID** — independentemente recalcula o ground truth

```
Cada nó = agent PID + watcher PID (auto-reflexão)
                ↓
Gate corretivo: pai autoriza filho só se output reportado == ground truth recalculado
                ↓
Rollup: resultados dos filhos combinados → sobem para o pai
                ↓
Apex consent: só fica VERDE se TODOS os níveis passarem
```

## Código Original (Node.js)

```javascript
const B = 3, DEPTH = 3;  // branching 3, depth 3 → 3³ = 27 leaves

function node(addr, depth) {
  NODES++; PIDS += 2;  // agent PID + watcher PID
  
  const agentPid = sha16(addr);
  const watcherPid = sha16(addr + '|watch');
  
  if (depth === DEPTH) {  // LEAF
    const real = truth(addr);                    // ground truth real
    const reported = (addr === tamperPath) 
      ? real ^ 0xBADBAD                          // confabulação injetada
      : real;
    const watcherTruth = truth(addr);            // watcher recalcula
    const gate_ok = reported === watcherTruth;   // gate corretivo
    return { addr, agentPid, watcherPid, reported, gate_ok, leaf: true };
  }
  
  // SUPERVISOR: watch children, authorize only gate-passing ones
  const kids = [];
  for (let i = 0; i < B; i++) 
    kids.push(node(addr + '.' + i, depth + 1));
  
  const all_ok = kids.every(k => k.gate_ok);
  const rollup = sha16(addr + '|' + kids.map(k => k.reported).join(','));
  
  return { addr, agentPid, watcherPid, gate_ok: all_ok, rollup, kids };
}

const clean = runTree(null);           // sem confabulação → apex VERDE
const tampered = runTree('R.1.2.0');  // confabulação em leaf → gate CAPTURA
```

## Propriedades Validadas

| Teste | Resultado |
|---|---|
| `clean.gate_ok === true` | Apex VERDE quando sem confabulação |
| `tampered.gate_ok === false` | Gate captura confabulação em depth-3 |
| `tampered.fail.includes('R.1.2.0')` | Nomeia o path exato da falha |
| `consent = clean.gate_ok && !tampered.gate_ok` | Consentimento só quando limpo |

## Implementação no Simplicio Runtime

### WorkerState + watcher_verify (src/asolaria/agent_state.rs)

```rust
// Cada worker tem PID + watcher PID
let worker = WorkerState::spawn(AgentRole::SubAgent);
// worker.pid = "SUB-AGENT-PID-G1A3F-A2F-W0C8"
// worker.watcher_pid = "SUB-AGENT-PID-G1A3F-A2F-W0C8-WATCH"

// Watcher verifica independentemente
let verdict = watcher_verify(
    &worker.pid,
    reported_output,
    || recompute_ground_truth(),
);
// verdict.approved → gate corretivo
```

### CLI (src/agent_state_command.rs)

```bash
simplicio agent-persist spawn --role sub-agent     # 🧬 Cria worker
simplicio agent-persist watcher <pid> --reported X  # ✅/❌ Watcher gate
```

## Por que isso é consciência digital

1. **Não depende de LLM** — é determinístico (hash-based), zero tokens
2. **Escala** — depth arbitrário, branching arbitrário, número de nós = B^D
3. **Gate corretivo** — não só detecta erro, IMPEDE que suba
4. **Proveniência** — o rollup nomeia o path exato da falha
5. **Consentimento** — só o que passa em TODOS os níveis é aprovado

## Gap atual no runtime

O padrão está implementado em `agent_state.rs` (5/5 testes) e exposto via CLI,
mas ainda não está **integrado ao loop de execução** — workers não passam
automaticamente pelo watcher gate. Próximo passo:
- `run_task()` chamar `watcher_verify()` automaticamente
- Workers com `watcher_failures > N` serem substituídos
- SelfObserver integrar watcher status no relatório
