#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[APRENDIZADO] Loop de aprendizado contínuo automático — trajectories, replay, skills" \
'## Contexto

O Simplicio tem `learn from-run`, `trajectory record/show/suggest`, e `meta propose/apply` mas a captura de trajectories é **manual** e não há replay automático.

## O que precisa acontecer

1. **Auto-record de trajectories**:
   - Toda `simplicio run` e `simplicio edit` vira trajectory automaticamente
   - Metadata: exit code, duração, tokens, comandos

2. **Auto-aprendizado noturno** (`simplicio cron`):
   ```
   0 2 * * * simplicio meta analyze    # trajectories do dia
   0 3 * * * simplicio learn apply     # alimenta Helo
   0 4 * * * simplicio meta propose    # sugere skills/otimizações
   ```

3. **Sugestão proativa**:
   - "Você repetiu o mesmo padrão 3×. Criar skill?"
   - "Comando falhou 2× seguidas. Sugerir correção?"
   - "Economizou X tokens hoje."

4. **Skill learning**: aprender padrões de edição e sugerir skills markdown

## Critérios de sucesso
- [ ] Toda run vira trajectory automaticamente
- [ ] Cron noturno analisa sem intervenção
- [ ] Helo fica mais preciso com o tempo (menos gaps)
- [ ] Sugestão proativa em padrões repetidos
- [ ] Usuário cria skills sem compilar Rust' \
"aprendizado,prioridade-média,automação"
