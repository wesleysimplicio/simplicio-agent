---
name: asolaria-agent-table
description: Agent definition table — agents como dados. Describe roles, prerequisites, toolsets, evidence, and deliverables in one table.
---

# Asolaria Agent Table

Use para definir agentes como dados, não como código espalhado.

## Estrutura
```json
{
  "agents": [
    {
      "name": "planner",
      "role": "triage and decomposition",
      "model": "large",
      "prerequisites": [],
      "toolset": ["read", "search", "map"],
      "prompt": "Break the task into bounded steps and acceptance criteria.",
      "deliverable": "plan.json",
      "evidence": "explicit ACs with receipts"
    },
    {
      "name": "coder",
      "role": "implementation",
      "model": "medium",
      "prerequisites": ["planner"],
      "toolset": ["edit", "validate"],
      "prompt": "Implement only the decided change.",
      "deliverable": "src/*.rs",
      "evidence": "passing validation"
    },
    {
      "name": "reviewer",
      "role": "adversarial review",
      "model": "small",
      "prerequisites": ["coder"],
      "toolset": ["read", "search"],
      "prompt": "Refute the change and cite any gap with file:line evidence.",
      "deliverable": "review.md",
      "evidence": "confirmed findings or pass"
    }
  ]
}
```

## Como executar
1. Carregue a tabela de agentes.
2. Verifique prerequisites antes de disparar cada agente.
3. Execute cada agente com o prompt, toolset e budget declarados.
4. Colete o deliverable e a evidência.
5. Passe para o próximo agente na cadeia só quando o anterior entregar o que foi pedido.

## Exemplo de pipeline
```
planner → coder → reviewer → report
         ↗       ↗
    (planner)  (coder)
    output     output
    plan.json  src/*.rs
```
