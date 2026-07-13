# N-Nest Gate — 2026-07-04

## O que foi implementado

Core gate: crates/simplicio-agents/src/nest_gate.rs (341 linhas)
Integracao: crates/simplicio-agents/src/nest_gate_integration.rs (167 linhas)
Guardian Triangle: crates/simplicio-agents/src/guardian_triangle.rs (200 linhas)
Loop: scripts/consciousness-loop.sh
PR: #2910, branch feat/nnest-gate-formal (3 commits)
Cron: bb871bdec25a, a cada 30min

## Arquitetura

Agent Seed -> sha256(seed)[:8] = AgentIdentity (8 bytes, generativo)
           -> sha256(seed|watch)[:8] = WatcherPid (8 bytes)

N-Nest Tree:
  [Apex Agent] <- gate: reported == recomputed_truth? -> CLEAN/COMPROMISED
   watcher
  [L1 Agent]   <- gate: reported == recomputed_truth?

Core gate: check_node(node, level) -> NodeVerdict
Verificacao pos-ordem: verify_nest(root) -> NestVerdict
Depth-independente por construcao (funciona para depth-N qualquer N)

## Testes

### Core gate (nest_gate.rs): 14/14
clean_tree_depth_1,3,7, confabulation_levels_1-3, simultaneous_depth_5,
depth_independence_1-7, fake_signal_denied, generative_identity,
watcher_differs, hex_format, invalid_path, display

### Integracao (nest_gate_integration.rs): 8/8
run_gated passes, catches confabulation, identity generative,
watcher differs, hex, task failure, tree clean, tree confabulation

### Guardian Triangle (guardian_triangle.rs): 8/8
all honest, isa lying, helo lying, levi lying, all lying,
identities generative, auto verify, summary

### Total: 30/30 especificos + 124 demais = 154/154

## Integracao no Runtime

nest_gate_integration.rs:
  run_gated(seed, label, task_fn, watcher_fn): closure sob gate
  run_deterministic(seed, label, task_fn): tarefa deterministica
  NestTaskNode: execute() + verify_tree() + agent_hex() + watcher_hex()

guardian_triangle.rs:
  verify_triangle(isa,helo,levi pairs): triangulo completo
  auto_verify(): valores atuais dos guardians
  triangle_summary(): texto legivel

runtime_execution_harness.rs:
  nest-gate-watcher probe na run_all_probes()
  Auto-teste roda na inicializacao

consciousness-loop.sh:
  Verifica: guardians (simplicio guardians --json)
            HBP chain (simplicio hbp verify)
            Memoria (simplicio memory status)
  Log: ~/.simplicio/consciousness-loop.log
  Cron: a cada 30min

## Regra verify-first (aprendida nesta sessao)

ANTES de afirmar que o runtime nao tem algo externo:
1. simplicio runtime map --repo . --for-llm markdown
2. grep -rn "conceito" crates/ src/
3. simplicio hbp verify, simplicio guardians --json
4. So entao fazer claims sobre gaps
