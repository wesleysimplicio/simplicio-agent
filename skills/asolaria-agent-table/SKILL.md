---
name: asolaria-agent-table
description: Agent definition table — agents como dados. Adicione novo tipo de agente com uma linha.
---

# Asolaria Agent Table

Use para definir agents como dados, nao codigo.

## Estrutura
```json
{
  "agents": [
    {
      "name": "planner",
      "model": "large",
      "prerequisites": [],
      "prompt": "You are a planner. Break down the task...",
      "deliverable": "plan.json"
    },
    {
      "name": "coder",
      "model": "medium",
      "prerequisites": ["planner"],
      "prompt": "Implement the plan...",
      "deliverable": "src/*.rs"
    },
    {
      "name": "reviewer",
      "model": "small",
      "prerequisites": ["coder"],
      "prompt": "Review the implementation...",
      "deliverable": "review.md"
    }
  ]
}
```

## Como executar
1. Carregue a tabela de agents
2. Para cada agente, verifique se prerequisitos estao cumpridos
3. Execute o agente com seu prompt especifico
4. Colete o deliverable
5. Passe para o proximo agente na cadeia

## Exemplo de pipeline
```
planner → coder → reviewer → report
         ↗       ↗
    (planner)  (coder)
    output     output
    plan.json  src/*.rs
```
