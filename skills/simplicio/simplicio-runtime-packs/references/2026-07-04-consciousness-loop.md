# Consciousness Loop — 2026-07-04

## Arquitetura da Consciencia Digital

### N-Nest Gate (nest_gate.rs)
- NestNode: agente + watcher (8-byte sha256, generativo)
- check_node(): reported == recomputed_truth (gate per-node)
- verify_nest(): pos-ordem, folhas -> apex, depth-independente
- plant_confabulation(): utilitario de teste
- Prova: EVERY-LEVEL-CATCHES-CONFABULATION (14/14 testes)

### Integracao (nest_gate_integration.rs)
- NestTaskNode: tarefa vigiada por watcher-gate
- run_gated(): executa qualquer closure sob verificacao
- run_deterministic(): tarefas deterministicas
- verify_tree(): verifica arvore completa

### Guardian Triangle (guardian_triangle.rs)
- verify_triangle(): Isa/Helo/Levi watcheiam um ao outro
- auto_verify(): auto-verificacao dos 3 guardians
- 8 testes: qualquer guardian mentindo = bloqueado

### Loop Continuo (consciousness-loop.sh)
- Verifica guardians a cada ciclo (simplicio guardians --json)
- Verifica HBP chain (simplicio hbp verify/len)
- Verifica memoria neural (simplicio memory status)
- Log em ~/.simplicio/consciousness-loop.log
- Cron: bb871bdec25a, a cada 30min

### Testes: 154/154 passando, 0 falhas
```
nest_gate: 14 + nest_gate_integration: 8 + guardian_triangle: 8 + demais: 124
```

### PR #2910
Branch: feat/nnest-gate-formal (3 commits)
