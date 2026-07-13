# External Repository Absorption Workflow

**Class:** Absorver repositório externo no ecossistema Simplicio.
**Exemplos:** Asolaria (JesseBrown1980), Meetily (Zackriya-Solutions/meeting-minutes).

## Princípios (validados pelo usuário)

1. **Extrair conceitos, NÃO copiar código.** Entender o padrão, verificar se já temos equivalente, implementar adaptado.
2. **Verificar ANTES de afirmar.** Rodar `simplicio runtime map` + `grep -rn` no código fonte antes de claimar gaps.
3. **Integrar, não criar do zero.** Se já existe algo similar, estender em vez de reimplementar.
4. **Implementar ou remover.** Código de referência que não compila = dívida técnica. Ou adapta ou apaga.

## Fluxo de Absorção

### Fase 1 — Descoberta
```
1. git clone <repo> para ~/.cache/simplicio-absorption/<nome>/
2. gh repo list <autor> --limit 200 → mapear todo o ecossistema
3. README de cada repo → extrair conceitos-chave (2-3 parágrafos)
4. Comparar: o que já temos? (grep -rn no simplicio-runtime)
5. Classificar gaps: crítico / quente / médio / baixo
```

### Fase 2 — Decisão (com o usuário)
```
Apresentar tabela comparativa:
  | Conceito | Já temos? | Gap real | Importância |

Decisões possíveis:
  - Absorver agora (PR nesta sessão)
  - Agendar (issue + milestone)
  - Rejeitar (documentar motivo, não deixar código morto)
```

### Fase 3 — Implementação
```
1. Criar issue: "feat: absorver <conceito> de <fonte>"
2. Branch: feat/<conceito>-<fonte>
3. Implementar adaptado (Rust/CLI, nunca copiar raw)
4. Testes: mínimo 5-8 testes do conceito absorvido
5. Regressão: cargo test -p simplicio-agents (deve passar tudo)
6. PR → merge imediato (nunca deixar PR aberto)
7. Atualizar memória neural: simplicio memory ingest
```

### Fase 4 — Documentação
```
1. Adicionar referência na skill simplicio-runtime-packs
2. Atualizar ECOSYSTEM_ABSORPTION_STATUS.md se existir
3. Registrar lição aprendida
```

## Exemplo: Parakeet STT (do Meetily)

**Fonte:** wesleysimplicio/meetily (fork de Zackriya-Solutions/meeting-minutes)
**Conceito:** Parakeet = modelo ASR baseado em ONNX Runtime, 4x mais rápido que Whisper
**Já tínhamos:** ✅ Whisper.cpp + voice_diarization.rs (diarização, extração semântica)
**Gap real:** Parakeet engine com suporte a GPU (CUDA/Metal/Vulkan) + Int8 quantizado

**Implementação:** `crates/simplicio-agents/src/parakeet.rs`
- `ParakeetEngine` — sync, com `load_model()` e `transcribe()`
- `ParakeetConfig` — model_path, quantization (Int8/FP32), provider (cpu/cuda/metal/vulkan)
- `TranscriptResult` — text, confidence, timestamps word-level
- Fallback automático: tenta Parakeet → se modelo não disponível, usa Whisper
- 8 testes

**Estrutura do Meetily que mapeamos:**
- `frontend/src-tauri/src/parakeet_engine/` — engine Rust
- `frontend/src-tauri/src/audio/transcription/parakeet_provider.rs` — provider trait
- `llama-helper/` — sumarização via llama.cpp (gap futuro)

## Exemplo: N-Nest Gate (do JesseBrown1980)

**Fonte:** JesseBrown1980/N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED
**Conceito:** Watcher-gate depth-independente: cada nó = agent PID + watcher PID, gate = reported == recomputed_truth
**Já tínhamos:** ✅ watcher.rs (WatcherPid 8-byte), seed.rs (DeterministicSeed)
**Gap real:** Árvore de verificação pós-ordem + proof EVERY-LEVEL-CATCHES-CONFABULATION

**Implementação:** `crates/simplicio-agents/src/nest_gate.rs` + `guardian_triangle.rs`
- `NestNode`, `check_node()`, `verify_nest()` — pós-ordem, depth-independente
- `guardian_triangle.rs` — Isa/Helo/Levi watcheiam um ao outro
- 22 testes

## Armadilhas Comuns

- ❌ Falar que não temos algo sem verificar primeiro (usuário corrigiu DURAMENTE)
- ❌ Copiar arquivos inteiros sem adaptar (viram código morto que não compila)
- ❌ Deixar código de referência que não é usado (dívida técnica)
- ✅ SEMPRE `cargo test -p simplicio-agents` no final para regressão
- ✅ SEMPRE PR + merge imediato (nunca deixar PR aberto)
