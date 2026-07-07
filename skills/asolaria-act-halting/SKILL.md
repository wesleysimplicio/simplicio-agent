---
name: asolaria-act-halting
description: Adaptive Computation Time — decide quando parar de iterar com base em confiança + evidência real. Economiza tokens sem fabricar saída.
---

# Asolaria ACT Halting

Use em loops de execução quando você quer parar cedo sem perder a prova de que terminou de verdade.

## Regra de parada
```rust
fn decide_halt(confidence: f64, iteration: u32, min_steps: u32, verified: bool) -> bool {
    verified && iteration >= min_steps && confidence > 0.85
}
```

## Como usar
1. Depois de cada iteração, peça ao modelo uma confiança de 0.0 a 1.0.
2. Só pare quando houver evidência real: teste passou, receipt válido, AC fechado, ou artefato verificável.
3. Se `confidence < 0.5`, troque de estratégia em vez de repetir o mesmo prompt.
4. Se `verified == false`, continue mesmo com confiança alta.
5. Se `iteration >= max_iterations`, pare com fallback.

## Prompt de confiança
```
Nivel de confianca no resultado atual (0.0 = nenhuma, 1.0 = certeza absoluta):
APENAS UM NUMERO, nada mais:
```

## Sinais de stall
- Mesmo erro repetido 3x → mude a abordagem ou reduza o escopo.
- Confiança alta sem evidência → não pare.
- Resultado vago sem receipt → trate como `not verified`.

## Exemplo
```python
iteration = 0
min_steps = 3
max_iterations = 10
while iteration < max_iterations:
    result = execute_step()
    confidence = get_confidence(result)
    verified = has_real_evidence(result)
    if decide_halt(confidence, iteration, min_steps, verified):
        break
    iteration += 1
```
