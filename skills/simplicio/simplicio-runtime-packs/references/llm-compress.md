# LlmCompress — Compressão paralela obrigatória de output pra LLM

**Módulo:** crates/simplicio-agents/src/llm_compress.rs (234 linhas)
**Testes:** 7/7 | **Release:** v2.3.0

## Regra: tokio compression MANDATORY em TODO output pra LLM

O usuário determinou: **tokio paralelo deve comprimir output de TODOS os comandos antes de enviar pro LLM.** Não é opcional — é camada obrigatória.

## O que faz
- Remove linhas DEBUG/TRACE
- Colapsa linhas similares consecutivas ("... N linhas similares omitidas")
- Relativiza caminhos (/Users/ → ~/)
- Mantém erros na íntegra (são mantidos SEMPRE)
- Reduce tokens de entrada em ~80%

## API
```rust
let mut comp = LlmCompressor::new();
let compressed = comp.compress(raw_output, "command_name");
println!("Ratio: {:.1}%", comp.ratio()); // bytes saved
println!("Tokens saved: {}", comp.estimated_tokens_saved());
```
