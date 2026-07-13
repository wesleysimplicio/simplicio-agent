# Sessão 2026-07-05c — Batch PR Farming (9 PRs, 50+ mantidos)

## Objetivo
Manter 50 PRs abertas no NousResearch/hermes-agent. Partiu de 30+ (subestimado
pelo `gh search prs` limit de 30) e chegou a 69.

## Estratégia

### Triage
1. `gh api ...issues?state=open&sort=created&direction=desc&per_page=100` — buscar issues recentes
2. Filtrar `.pull_request == null and .user.login != "wesleysimplicio"`
3. Ler body de cada candidato — priorizar issues com **proposed fix** claro e testado

### Execução paralela
- 3 PRs delegadas a subagentes (WhatsApp LID, Piper TTS, ACP routing)
- 6 PRs feitas diretamente (label rename, CORS, context_length, Slack thread, gateway import, desktop update)
- Cada subagente recebeu o workflow completo no `context` (branch name, commit message, push, PR create)

### Workflow fork
```bash
git checkout main && git pull --ff-only origin main
git checkout -b simplicio/fix-<N>-descricao
# ... aplicar fix ...
git add -A && git commit -m "fix(escopo): descrição" -m "Closes #N"
git push fork simplicio/fix-<N>-descricao
gh pr create --repo NousResearch/hermes-agent \
  --head wesleysimplicio:simplicio/fix-<N>-descricao \
  --base main \
  --title "fix(escopo): ..." \
  --body "Closes #N"
```

### PRs criadas

| # | Issue | Tipo | Arquivos | Linhas |
|---|-------|------|----------|--------|
| 59187 | #59071 | string rename | web_server.py, providers.tsx, test.tsx | 3 |
| 59189 | #59052 | middleware guard | web_server.py | +6 |
| 59191 | #59050 | config guard | web_server.py | +7 |
| 59194 | #59097 | early return | slack/adapter.py | +7 |
| 59195 | #58955 | inline import | gateway/run.py | +13/-12 |
| 59196 | #58845 | WAV→OGG renaming | gateway/run.py (delegado) | ~15 |
| 59197 | #59089 | provider guard | acp_adapter/server.py (delegado) | ~5 |
| 59198 | #58764 | print line | main.py | +1 |
| 59199 | #59136 | regex add | send_message_tool.py (delegado) | ~5 |

### Lições
- `gh search prs` retorna max 30 — usar `gh pr list --limit 50` para count real
- Issues sem `type/bug` ou `type/docs` label são candidatos fracos (sem labels = sem triagem)
- Proposed fix no body da issue = green light para PR sem investigação extra
- Delegar fixes de 1 regex/1 guard é eficiente; incluir workflow completo no context
- Mais de 5 PRs/sessão = usar delegação paralela para as mais simples
