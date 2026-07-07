---
name: asolaria-act-halting
description: Adaptive Computation Time — decide quando parar de iterar baseado na confianca do resultado. Economiza tokens.
---

# Asolaria ACT Halting

Use em loops de execucao para evitar iteracoes desnecessarias.

## Regra de parada
```
fn decide_halt(confidence: f64, iteration: u32, min_steps: u32) -> bool {
    iteration >= min_steps && confidence > 0.85
}
```

## Como usar
1. A cada iteracao, peca ao LLM para estimar confianca (0.0 a 1.0)
2. Se confidence > 0.85 E iteration >= min_steps → PARE
3. Se confidence < 0.5 → mude de estrategia (nao repita o mesmo prompt)
4. Se iteration >= max_iterations → PARE (fallback)

## Prompt de confianca
```
Nivel de confianca no resultado atual (0.0 = nenhuma, 1.0 = certeza absoluta):
APENAS UM NUMERO, nada mais:
```

## Exemplo
```python
iteration = 0
min_steps = 3
max_iterations = 10
while iteration < max_iterations:
    result = execute_step()
    confidence = get_confidence(result)
    if iteration >= min_steps and confidence > 0.85:
        break
    iteration += 1
```
