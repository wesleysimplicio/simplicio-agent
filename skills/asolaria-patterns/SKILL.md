---
name: asolaria-patterns
description: Port dos padrões Asolaria (JesseBrown1980) para o Simplicio Runtime como primitivas determinísticas testáveis — N-Nest cosign/corrective gate, HRM two-level planner, BEHCS-256 supervisor federado.
---

# Asolaria Patterns — Port Determinístico

Use este skill quando evoluir o `simplicio-runtime` absorvendo padrões do
ecossistema Asolaria (N-Nest-Prime, HRM, BEHCS-256). Todo padrão aqui é uma
**primitiva determinística testável**, nunca um stub LLM.

Princípio do `simplicio-runtime-asolaria-porting`: prefira transform puro,
gate explícito, persistência tipada. O runtime é o *determinism kernel*; estes
padrões são bibliotecas Python/Rust puras que o `simplicio-agent` consome.

## Padrões portados

### 1) N-Nest — Cosign + Corrective Gate (`lib/nest_cosign.py`)
Implementação original do contrato de N-Nest depth-3, sem copiar código externo.
- Cada nó = agente PID + watcher PID (2 PIDs) que recomputa a ground-truth.
- Gate corretivo: pai autoriza filho só se `reported == watcher_recomputed_truth`.
- Roll-up de *consent*: só dispara se TODOS os níveis passam.
- Tamper test: injeta confabulação em folha 3 níveis fundo; gate TEM que pegar.
- Aproveita `ReceiptChain` (hash-chained) do `simplicio-fabric` para cosign.

### 2) N-Nest depth-N prime (`lib/nest_depthn.py`)
Implementação original de uma árvore hash binária determinística com `N=7`.
Cada nó mantém o hash verdadeiro recomputado pelo watcher, o hash reportado,
o gate local e `fail_by_depth`; uma confabulação é detectada no próprio nível e
propagada ao apex sem perder a profundidade.

O espelho correspondente em `simplicio-runtime` está **UNVERIFIED** nesta
árvore do agente: não há checkout/runtime externo disponível para confirmar
paridade, portanto nenhum estado de paridade é declarado.

### 3) HRM — Two-Level Planner (`lib/hierarchical_planner.py`)
Port de `HRM/models/hrm/hrm_act_v1.py` (loop H/L sem torch).
- High-level (LENTO): re-planeja a cada `H_cycles` passos.
- Low-level (RÁPIDO): executa `L_cycles` micro-passos entre re-planejos.
- Carry state: `z_H` / `z_L` propagados (aqui: dicts/strings determinísticos).

### 4) BEHCS-256 — Supervisor Federado (`lib/behcs_supervisor.py`)
Port de `asolaria-behcs-256/tools/behcs/behcs-agent-operator.js`.
- Cube/register NDJSON com GC bounded (truncate em MAX).
- Hilbert address = sha256_16 (compat `asolaria_hbi_hbp::agt`).
- Loop de operador: screenshot→check→corrige→verify→GC, max loops.

## Uso
```bash
python3 skills/asolaria-patterns/lib/nest_cosign.py --selftest
python3 skills/asolaria-patterns/lib/hierarchical_planner.py --selftest
python3 skills/asolaria-patterns/lib/behcs_supervisor.py --selftest
python3 skills/asolaria-patterns/lib/nest_depthn.py --selftest
python3 -m pytest skills/asolaria-patterns/tests/ -q
```

## Verificação (obrigatória)
Cada padrão tem `--selftest` e teste pytest que PROVA o comportamento:
- `nest_cosign`: run limpo → apex VERIFIED; run com tamper → apex UNVERIFIED + path nomeado.
- `hierarchical_planner`: H re-planeja N vezes, L executa L_cycles cada.
- `behcs_supervisor`: register estoura MAX → truncate p/ últimas MAX linhas.
- `nest_depthn`: árvore limpa verifica; cada nível 1..7 captura exatamente
  `@depthN`; `N=7` é primo e a árvore tem 255 nós.

## Pitfalls
- Não substitua gate por stub. O gate deve *morder* (tamper test obrigatório).
- Não use torch/LLM no core — estes são primitivas puras.
- Mantenha compat de hashing com `asolaria_hbi_hbp` (sha256_16 = `AGT-`+16hex).
