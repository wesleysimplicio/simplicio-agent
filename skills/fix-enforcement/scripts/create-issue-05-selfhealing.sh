#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[SELF-HEALING] Implementar recuperação automática de falhas (crash, lock, deadlock)" \
'## Contexto

O Simplicio crasha frequentemente com SIGKILL por RAM, lock contention (`repo.lock`), deadlock de enforcement, e agents órfãos. Hoje a recuperação é **100% manual** (`rm -f .simplicio/locks/repo.lock`).

## O que precisa acontecer

1. **`simplicio recover --auto`** — recovery automático:
   - Limpa locks órfãos (> 5 min sem heartbeat)
   - Mata agents com timeout
   - Restaura estado do `.simplicio/`
   - Relatório do que foi limpo

2. **Health endpoint HTTP**:
   - Status do runtime, heartbeat dos agents, uso de RAM/CPU
   - Integridade dos locks

3. **Watchdog systemd/LaunchAgent**:
   - Reinicia automaticamente em crash
   - Health check periódico
   - Notificação se auto-recovery falha

4. **Graceful degradation**:
   - RAM > 80% → reduz agents (normal → low)
   - Lock contention → backoff exponencial
   - Enforcement deadlock → bypass automático

## Critérios de sucesso
- [ ] `simplicio recover --auto` limpa locks em < 1s
- [ ] Health endpoint retorna status JSON
- [ ] Watchdog reinicia runtime em < 10s após crash
- [ ] Graceful degradation automática em pico de RAM' \
"self-healing,prioridade-alta,infra"
