# Tokio/tokill — Entendimento Correto (03/07/2026)

## O que é Tokyo/Tokio

Tokyo = **Tokio** (Rust async runtime). O crate `simplicio-tokill` = **Toki**o + **kill**.
Não é cache. É o async runtime que gerencia **CPU e concorrência**.

## O que tokill faz

**Tokill NÃO acelera comandos.** Ele **filtra output** de comandos shell para reduzir
tokens enviados ao LLM. O ganho é em **economia de tokens**, não em velocidade.

| Filtro | Alvo | Redução |
|---|---|---|
| `filter_git` | git status, diff, log | 40-70% |
| `filter_build` | cargo build, make | 60-80% |
| `filter_test` | cargo test, pytest | 50-75% |
| `filter_gh` | gh CLI | 40-60% |
| `filter_file_ops` | ls, cat, grep | 30-50% |

O compressor nativo **TOON** (`toon_encode.rs`) é o que comprime output JSON do runtime,
atingindo até **95%** em payloads verbosos.

## Paralelismo real

O runtime usa Tokio async:
- 32 workers de modelo (concorrência real, não simulada)
- 600 slots lógicos de agente
- Cada delegate_task ou agent delegate = uma task Tokio
- CPU gerenciada pelo Tokio runtime, não por shell & ou threads manuais

## Performance medida

14+ comandos medidos em benchmark com 3 agents paralelos:
- Média: ~290ms por comando
- Mais rápido: `license status` (136ms)
- Mais lento: `version` (924ms, ~1027 tokens)
- TOON comprime JSON em até 95%

## Bugs encontrados

- `governor simulate --json` trava (modo sem --json funciona em 479ms)
