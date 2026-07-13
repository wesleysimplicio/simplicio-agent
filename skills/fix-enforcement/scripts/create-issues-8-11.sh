#!/usr/bin/env bash
# Continuation: issues 8-12 (Hermes parity extras)
set -euo pipefail

REPO="${1:-wesleysimplicio/simplicio-runtime}"

create_issue() {
    local title="$1"
    local body="$2"
    local labels="$3"
    echo "Criando: $title"
    gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels"
    echo "---"
}

# ========================================================================
# ISSUE 8: Telemetria e observabilidade
# ========================================================================
create_issue \
"[OBSERVABILIDADE] Sistema de telemetria e dashboards de uso/performance" \
'## Contexto

O Simplicio não tem dashboards ou métricas de:
- Quantas runs por dia/semana
- Taxa de sucesso/erro dos gates
- Quanto tempo cada pipeline leva
- Quais comandos são mais usados
- Crash tracking
- Uso de memória/CPU por operação

O `simplicio insights` existe mas é basicão (só analytics de sessão via SQLite).

## O que precisa acontecer

1. **Métricas instrumentadas no runtime**:
   - Contadores: runs, edits, validations, gates triggered
   - Timers: tempo médio de cada operação
   - Gauges: agents ativos, uso de RAM/CPU
   - Histogramas: tamanho de mapas, tempo de compilação

2. **`simplicio metrics`** — comando para ver métricas:
   ```
   simplicio metrics                    # Dashboard no terminal
   simplicio metrics --json             # Export JSON
   simplicio metrics --prometheus       # Export Prometheus format
   simplicio metrics --since 7d         # Últimos 7 dias
   ```

3. **Dashboard HTML local**:
   - Gráficos de uso (chart.js ou similar)
   - Timeline de runs
   - Top comandos
   - Crash history
   - Performance over time

4. **Crash reporting**:
   - Captura de panics/unwinds com backtrace
   - `simplicio dump` já existe (diagnostics dump)
   - Expandir para enviar crash reports para arquivo local
   - `simplicio crash list|show`

5. **Exportação**:
   - `simplicio metrics export --format json|csv`
   - Integração com `savings` para correlacionar economia x performance

## Armazenamento

- SQLite local (`~/.simplicio/metrics.db`)
- Rotação automática (keep last 90 dias)
- Compressão opcional

## Critérios de sucesso

- [ ] `simplicio metrics` mostra dashboard funcional
- [ ] Crash tracking captura panics com backtrace
- [ ] Export para JSON/Prometheus funciona
- [ ] Dados de savings correlacionados com performance
- [ ] Rotação automática sem intervenção manual' \
"observabilidade,prioridade-média"

# ========================================================================
# ISSUE 9: Loop de aprendizado mais agressivo
# ========================================================================
create_issue \
"[APRENDIZADO] Loop de aprendizado contínuo automático — trajectories, replay, skills" \
'## Contexto

O Simplicio tem `simplicio learn from-run`, `trajectory record/show/suggest`, e `meta propose/apply`, mas:

- A captura de trajectories é **manual** (tem que chamar `trajectory record <session>` explicitamente)
- Não há replay automático de sessions anteriores para extrair padrões
- O neural memory (Helo) só aprende quando explicitamente alimentado
- Skills em Rust precisam ser compiladas — não podem ser criadas em markdown like Hermes

## O que precisa acontecer

1. **Auto-record de trajectories**:
   - Toda `simplicio run` vira trajectory automaticamente
   - Toda `simplicio edit` vira trajectory
   - Metadata: exit code, duração, tokens gastos, comandos executados

2. **Auto-aprendizado noturno** (`simplicio cron`):
   ```
   0 2 * * * simplicio meta analyze    # Analisa trajectories do dia
   0 3 * * * simplicio learn apply     # Aplica aprendizados ao Helo
   0 4 * * * simplicio meta propose    # Sugere novas skills/otimizações
   ```

3. **Sugestão proativa**:
   - "Percebi que você usou o mesmo padrão 3 vezes. Quer criar uma skill?"
   - "Esse comando falhou 2 vezes seguidas. Quer que eu sugira uma correção?"
   - "Você economizou X tokens hoje usando Simplicio em vez de chamadas diretas"

4. **Skill learning** (ver issue específica de skills em markdown):
   - Aprender padrões de edição e sugerir como skills
   - Skills em Python para lógica, markdown para documentação

## Critérios de sucesso

- [ ] Toda run tem trajectory auto-registrada
- [ ] Cron noturno analisa trajectories sem intervenção
- [ ] Helo fica mais preciso com o tempo (medido: menos gaps)
- [ ] Sugestão proativa aparece em sessões com padrões repetidos
- [ ] Usuário pode criar skills sem compilar Rust' \
"aprendizado,prioridade-média,automação"

# ========================================================================
# ISSUE 10: Integração LLM multi-provedor
# ========================================================================
create_issue \
"[LLM] Integração profunda com múltiplos provedores LLM + roteamento inteligente" \
'## Contexto

O Simplicio tem **código compilado para 5 provedores LLM** (OpenRouter, Anthropic, DeepSeek, Gemini, Mistral) mas **só OpenRouter é wireado como backend de inferência**. Os outros 4 têm centenas de linhas de código para catalogar modelos e validar API keys, mas não são usados no pipeline de `chat`/`run`.

Problemas:
- Dependência única de OpenRouter = SPOF (se OpenRouter cai, nada funciona)
- Não há fallback automático entre provedores
- Não há roteamento inteligente (tarefa simples → modelo barato, tarefa complexa → modelo forte)
- Modelo local (`llama-server`) está no PATH mas não é backend padrão

## O que precisa acontecer

1. **Roteamento inteligente**:
   ```
   Tarefa simples/ determinística → modelo local (qwen 2.5-coder 1.5B)
   Tarefa média → modelo barato (DeepSeek, Mistral)
   Tarefa complexa/criativa → modelo forte (Claude, GPT, Gemini)
   ```
   - `simplicio model routing` — configura e gerencia rotas
   - Auto-detect: baseado no tipo de tarefa (plan vs edit vs run vs chat)
   - Custo-aware: prefere o mais barato que atende ao requisito

2. **Fallback automático**:
   - Se provedor primário falha (timeout, 429, 500) → provedor secundário
   - Se todos os remotos falham → modelo local
   - Se modelo local falha → fallback para regras determinísticas

3. **Wirear provedores existentes**:
   - `integration_anthropic.rs` → pipeline de chat/run
   - `integration_deepseek.rs` → pipeline de chat/run
   - `integration_gemini.rs` → pipeline de chat/run
   - `integration_mistral.rs` → pipeline de chat/run

4. **Modelo local como cidadão de primeira classe**:
   - `simplicio model local` — gerencia modelo local (start/stop/status)
   - Suporte a llama.cpp, ollama, ou API compatível com OpenAI
   - Auto-download do modelo na primeira execução

## Critérios de sucesso

- [ ] Roteamento inteligente: tarefa simples usa modelo barato
- [ ] Fallback: se provedor A falha, usa B automaticamente
- [ ] Todos os 5 provedores wireados
- [ ] Modelo local funciona como backend padrão offline
- [ ] `simplicio model status` mostra todos os provedores + health' \
"llm,prioridade-média,integração"

# ========================================================================
# ISSUE 11: Remover código morto
# ========================================================================
create_issue \
"[LIMPEZA] Mutirão de remoção de código morto: ~189 dead_code allow, 2 arquivos não compilados, 4 integrações não wireadas" \
'## Contexto

O Simplicio acumulou uma quantidade significativa de código morto:

1. **`#![allow(dead_code)]`** em ~50+ módulos (~189 ocorrências) — warnings suprimidos, impossível saber o que está morto
2. **`src/final_modules.rs`** (~6.7KB) — CoverageGaps, DeadCodeMapper, ConflictHeatmap, CrdtDoc, ReplState — **nunca compilados** (não declarados como `mod`)
3. **`src/provider_command.rs`** (~72KB) — 57 funções de resolução de provedor **duplicadas** do dispatch em main.rs
4. **4 integrações LLM** (Anthropic, DeepSeek, Gemini, Mistral) — código compilado mas **não wireado no pipeline**
5. **Vários módulos suspeitos**: `seguranca_audit.rs`, `navegacao.rs`, `voice_orb.rs`, `wake_on_voice.rs` — compilados mas provavelmente nunca executados

## Impacto

- Código morto = peso morto: aumenta tempo de compilação
- Esconde bugs (dead_code permite código quebrado sem warning)
- Engana auditoria e levantamento de capacidades
- Aumenta superfície de segurança desnecessariamente

## Regras da limpeza

Cada item deve ser:
1. **Ou testado** (adicionar `#[cfg(test)]` e testes que provem que funciona)
2. **Ou removido** (deletar arquivo e remover referências)
3. **Ou feature-gated** (adicionar `#[cfg(feature = "experimental")]`)

## O que precisa acontecer

### Fase 1: Remoção segura
- `final_modules.rs` → deletar (não compilado, nunca usado)
- `provider_command.rs` → integrar ou deletar (72KB de duplicação)
- `voice_orb.rs`, `wake_on_voice.rs` → feature gate `voice` ou deletar

### Fase 2: Decidir destino
- `seguranca_audit.rs`, `navegacao.rs` → testar ou deletar
- `changelog_command.rs`, `dashboard_command.rs` → testar ou deletar
- 4 integrações LLM → wirear como backend ou feature-gate

### Fase 3: Remover `#![allow(dead_code)]`
- Módulo por módulo: remover allow, compilar, ver o que está realmente morto
- Adicionar testes para o que está vivo
- Feature gate para o que é experimental mas válido

## Critérios de sucesso

- [ ] `final_modules.rs` removido
- [ ] `provider_command.rs` resolvido (integrado ou deletado)
- [ ] Módulos de voz feature-gated
- [ ] `#![allow(dead_code)]` reduzido de ~50 módulos para < 5
- [ ] Compilação sem warnings' \
"limpeza,prioridade-alta,refatoração"

echo ""
echo "=== Issues 8-11 criadas! ==="
