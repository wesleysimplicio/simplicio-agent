#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[LLM] Integração profunda com múltiplos provedores LLM + roteamento inteligente" \
'## Contexto

O Simplicio tem código compilado para 5 provedores (OpenRouter, Anthropic, DeepSeek, Gemini, Mistral) mas **só OpenRouter é wireado**. Os outros 4 têm centenas de linhas de código morto.

Problemas:
- Dependência única de OpenRouter = SPOF
- Sem fallback automático entre provedores
- Sem roteamento inteligente (tarefa simples → modelo barato)
- Modelo local (`llama-server`) não é backend padrão

## O que precisa acontecer

1. **Roteamento inteligente**:
   ```
   Tarefa simples → modelo local (qwen 2.5-coder)
   Tarefa média → modelo barato (DeepSeek, Mistral)
   Tarefa complexa → modelo forte (Claude, GPT, Gemini)
   ```
   - `simplicio model routing` — gerencia rotas
   - Auto-detect baseado no tipo de tarefa
   - Custo-aware: mais barato que atende

2. **Fallback automático**
   - Primário falha → secundário
   - Todos remotos falham → local
   - Local falha → regras determinísticas

3. **Wirear provedores existentes**:
   `integration_anthropic.rs`, `integration_deepseek.rs`, `integration_gemini.rs`, `integration_mistral.rs`

4. **Modelo local como cidadão de primeira classe**:
   - `simplicio model local start|stop|status`
   - Suporte a llama.cpp, ollama
   - Auto-download na primeira execução

## Critérios de sucesso
- [ ] Roteamento inteligente: tarefa simples usa modelo barato
- [ ] Fallback automático entre provedores
- [ ] Todos os 5 provedores wireados
- [ ] Modelo local funciona offline
- [ ] `simplicio model status` mostra todos + health' \
"llm,prioridade-média,integração"
