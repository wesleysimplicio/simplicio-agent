#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[AGENT-IPC] Implementar comunicação inter-processos (agent-ipc/v1) — schema existe há 8 meses sem implementação" \
'## Contexto

O schema `agent-ipc/v1` existe como arquivo `.json` em `schemas/` há **mais de 8 meses**, mas **nunca foi implementado**. Isso significa que:

- Os **23 módulos em `src/organism/`** (arquitetura de "organismo digital") são código não testado ou morto — não há comunicação real entre processos Simplicio
- `simplicio agents delegate` provavelmente não funciona em produção multi-processo
- O ecossistema de agentes paralelos (64-600 workers) não tem backbone de comunicação
- Schemas como `agent-queue-item`, `agent-lease`, `agent-escalation-policy` existem mas nunca foram exercitados

## O que precisa acontecer

1. **Implementar agent-ipc via stdin/stdout JSON-RPC** (leve, zero dependências externas):
   - Protocolo request/response com message IDs
   - Suporte a notificações (fire-and-forget)
   - Timeout e retry configuráveis
   - Autenticação via token shared

2. **Wirear no `organism/`**:
   - Cada módulo do organismo se comunica via agent-ipc
   - Heartbeat entre agents
   - Message routing baseado em capability

3. **Atualizar schemas**:
   - `agent-ipc/v1` — tornar protocolo real com exemplos
   - `agent-lease/v1` — implementar lease system
   - `agent-escalation-policy/v1` — implementar escalação

## Critérios de sucesso

- [ ] Dois processos Simplicio se comunicam via agent-ipc
- [ ] `simplicio agents delegate` funciona com workers reais
- [ ] organism/ tem testes de comunicação
- [ ] Schemas antigos atualizados ou removidos
- [ ] Documentação do protocolo' \
"agent-ipc,prioridade-alta,arquitetura"
