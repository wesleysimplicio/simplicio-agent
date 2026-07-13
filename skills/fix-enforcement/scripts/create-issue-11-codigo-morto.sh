#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[LIMPEZA] Mutirão de remoção de código morto: ~189 dead_code allow, 2 arquivos não compilados, 4 integrações não wireadas" \
'## Contexto

Código morto acumulado no Simplicio:
1. **`#![allow(dead_code)]`** em ~50+ módulos (~189 ocorrências) — warnings suprimidos
2. **`src/final_modules.rs`** (~6.7KB) — **nunca compilado** (não declarado como `mod`)
3. **`src/provider_command.rs`** (~72KB) — 57 funções duplicadas do dispatch em main.rs
4. **4 integrações LLM** wireadas em schema mas não no pipeline
5. **Vários módulos suspeitos**: `seguranca_audit.rs`, `navegacao.rs`, `voice_orb.rs`

## Regras
Cada item: ou é **testado**, ou **removido**, ou **feature-gated**.

## O que precisa acontecer

### Fase 1: Remoção segura
- `final_modules.rs` → deletar
- `provider_command.rs` → integrar ou deletar
- `voice_orb.rs`, `wake_on_voice.rs` → feature gate `voice`

### Fase 2: Decidir destino
- `seguranca_audit.rs`, `navegacao.rs` → testar ou deletar
- 4 integrações LLM → wirear ou feature-gate

### Fase 3: Remover `#![allow(dead_code)]`
- Módulo por módulo: remover allow, compilar, ver o que está morto
- Testar o que está vivo, gatear o que é experimental

## Critérios de sucesso
- [ ] `final_modules.rs` removido
- [ ] `provider_command.rs` resolvido
- [ ] Módulos de voz feature-gated
- [ ] `#![allow(dead_code)]` reduzido de ~50 módulos para < 5
- [ ] Compilação sem warnings' \
"limpeza,prioridade-alta,refatoração"
