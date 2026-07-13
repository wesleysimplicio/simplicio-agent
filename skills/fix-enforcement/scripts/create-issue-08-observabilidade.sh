#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[OBSERVABILIDADE] Sistema de telemetria e dashboards de uso/performance" \
'## Contexto

O Simplicio não tem dashboards de métricas: runs/dia, taxa de sucesso dos gates, tempo de pipeline, comandos mais usados, crash tracking, uso de RAM/CPU.

## O que precisa acontecer

1. **Métricas instrumentadas no runtime**:
   - Contadores: runs, edits, validations, gates triggered
   - Timers: tempo médio de cada operação
   - Gauges: agents ativos, RAM/CPU
   - Histogramas: tamanho de mapas, tempo de compilação

2. **`simplicio metrics`** — comando para ver métricas:
   - Dashboard no terminal, export JSON, export Prometheus
   - `--since 7d` para período

3. **Dashboard HTML local**:
   - Gráficos de uso (chart.js)
   - Timeline de runs, top comandos, crash history

4. **Crash reporting**:
   - `simplicio dump` já existe — expandir para capturar panics com backtrace
   - `simplicio crash list|show`

5. **Armazenamento**: SQLite local (`~/.simplicio/metrics.db`), rotação 90 dias

## Critérios de sucesso
- [ ] `simplicio metrics` mostra dashboard funcional
- [ ] Crash tracking captura panics com backtrace
- [ ] Export JSON/Prometheus funciona
- [ ] Rotação automática sem intervenção' \
"observabilidade,prioridade-média"
