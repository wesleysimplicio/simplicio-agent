#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[HERMES-PARITY] Alcançar paridade com Hermes em tools, flexibilidade e integração de plataformas" \
'## Contexto

O Hermes tem vantagens em várias áreas que o Simplicio precisa alcançar. Esta issue consolida todos os gaps.

## Tools que faltam

| Tool | Hermes | Simplicio |
|------|--------|-----------|
| Vision/image analysis | ✅ vision_analyze | ❌ Não tem |
| TTS / STT | ✅ Nativo | ❌ Não tem |
| Skills hub público | ✅ skills hub | ❌ Não tem |
| Session search (FTS5) | ✅ session_search | ❌ Não tem |
| Checkpoints (snapshots) | ✅ filesystem | ❌ Não tem |
| delegate_task real | ✅ subagentes | agents delegate existe mas não testado |

## Flexibilidade

| Funcionalidade | Hermes | Simplicio |
|----------------|--------|-----------|
| Adicionar tool | 1 .py, reload | Compilar Rust 2-5 min |
| Mudar provider | Imediato | Rebuild ou config |
| Gateway hot-swap | Imediato | Rebuild |
| Multi-channel personas | channel_prompts | ❌ Não tem |
| Webhook subscriptions | ✅ Nativo | webhook existe |
| Plugin system | Python plugins | Rust compilado |

## O que precisa acontecer

### Fase 1: Crítico
- [ ] Vision/image analysis tool
- [ ] TTS / STT tools
- [ ] Session search (FTS5 nas sessions)
- [ ] Skills em markdown (issue #12)
- [ ] Testes (issue #2)

### Fase 2: Médio
- [ ] Skills hub público
- [ ] Checkpoints (snapshots pre-edit)
- [ ] Hot-reload de tools (sem rebuild)
- [ ] Multi-channel personas no gateway
- [ ] Docs completas

### Fase 3: Ecossistema
- [ ] Contributing guide
- [ ] CI/CD completo
- [ ] Skills catalog comunitário

## Nota arquitetural
> Rust é motor central, camadas externas em Python

Core em Rust (performance), skills/scripts/adapters em Python (flexibilidade)' \
"hermes-parity,prioridade-média,ecossistema"
