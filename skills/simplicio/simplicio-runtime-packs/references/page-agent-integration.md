# Page Agent (Alibaba) — Integração com Simplicio Runtime

Schema: `simplicio.page-agent-bridge/v1` · PRs: #2826, #2827, #2828, #2829

## O que é

[Page Agent](https://github.com/alibaba/page-agent) é um framework de automação de browser
da Alibaba com pipeline DOM inteligente (FlatDomTree → simplified HTML → LLM) + LLM reflection.

## Arquitetura da Bridge

```
Simplicio Agent
  ├── Injeta: SIMPLICIO_PAGE_AGENT_DIR (auto-detect)
  ├── Injeta: SIMPLICIO_LLM_MODEL      (provider configurado)
  ├── Injeta: SIMPLICIO_LLM_API_KEY    (credencial)
  ├── Injeta: SIMPLICIO_LLM_BASE_URL   (proxy Simplicio se ativo)
  └── Passa:  SIMPLICIO_PAGE_AGENT_URL (URL alvo)
                      ↓
        page-agent-bridge.sh <url>
                      ↓
    simplicio browser navigate <url>
                      ↓
    CDP: abre navegador + injeta PageAgentController
                      ↓
    FlatDomTree + click + input + scroll
```

## Componentes Page Agent

| Package | npm | Função |
|---|---|---|
| `@page-agent/core` | `page-agent` | PageAgentCore (headless) |
| `@page-agent/llms` | `@page-agent/llms` | LLM client + MacroToolInput |
| `@page-agent/page-controller` | `@page-agent/page-controller` | DOM ops + FlatDomTree |
| `@page-agent/ui` | `@page-agent/ui` | Panel + i18n |
| Extension | — | WXT + React browser extension |

## Pipeline DOM

1. `pageController.updateTree()` → `FlatDomTree`
2. `pageController.getSimplifiedHTML()` → texto otimizado para LLM
3. LLM processa → ações (click, input, scroll)
4. `pageController.clickElement(index)` → executa

## Injeção via CDP

Quando `simplicio browser navigate <url>` abre o navegador, o controller do
Page Agent é injetado na página via CDP `Page.addScriptToEvaluateOnNewDocument`.

O content script (`packages/extension/src/entrypoints/content.ts`) expõe:
- `initPageController()` → DOM pipeline
- `MultiPageAgent` → agente multi-página
- Comunicação via `window.postMessage`

## Uso

```bash
# 1. Clonar Page Agent
git clone https://github.com/alibaba/page-agent.git ~/Projetos/ai/page-agent

# 2. Bridge (tudo injetado automaticamente)
bash examples/page-agent-bridge/page-agent-bridge.sh https://exemplo.com
```

## Arquivos

- `examples/page-agent-bridge/page-agent-bridge.sh` — bridge shell script
- `examples/page-agent-bridge/README.md` — documentação
