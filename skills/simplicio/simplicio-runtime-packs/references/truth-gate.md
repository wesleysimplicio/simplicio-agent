# Truth Gate — Savings Proof Enforcement

Schema: `simplicio.truth-gate/v1` · Issue: #2807 · PR: #2808

## O que é

Gate que impede `proof-kind=measured` sem evidência real. Criado após o usuário flagrar
que savings estavam sendo fabricados (85k vs 650k = chute, não medida).

## Como funciona (Rust, src/main_parts/chunk_96_truth_gate.rs)

```
measured + sem --evidence-ref          → REJEITADO (erro: "measured requer --evidence-ref")
measured + --evidence-ref path/inexistente → REJEITADO (erro: "evidência não encontrada")
measured + --evidence-ref path/real     → ACEITO (exibe "MEASURED| Evidência verificada: path")
estimated + sem ref                     → ACEITO (sem verificação)
benchmark + sem ref                     → ACEITO (sem verificação)
```

## Testes unitários

```rust
#[test]
fn test_estimated_passes()              // estimated sem ref → Ok
#[test]
fn test_measured_sem_evidencia_rejeita() // measured sem ref → Err
#[test]
fn test_measured_com_evidencia_inexistente_rejeita() // measured com ref fake → Err
#[test]
fn test_benchmark_passes()              // benchmark sem ref → Ok
```

## Uso correto

```bash
# Medido com evidência
simplicio savings record --spent 1687 --baseline 20474317 \
  --source prove-real \
  --task "descrição" \
  --proof-kind measured \
  --evidence-ref .simplicio/proof/prove-real-xxx.json

# Estimado (sem evidência)
simplicio savings record --spent 5000 --baseline 50000 \
  --source cli \
  --task "descrição" \
  --proof-kind estimated
```

## Histórico

- 2026-07-03: Criado após usuário detectar savings fabricados
- Chunk `chunk_96_truth_gate.rs` mergeado no main via PR #2808
