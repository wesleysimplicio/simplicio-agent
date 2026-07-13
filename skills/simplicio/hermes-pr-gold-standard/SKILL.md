---
name: hermes-pr-gold-standard
description: Padrão ouro para PRs aprovadas no Hermes Agent — validado contra PRs reais mergeadas.
version: 2.0.0
author: Simplicio Agent
license: MIT
platforms: [macos, linux]
---

# Padrão Ouro para PRs Aprovadas no Hermes Agent

## Regra #0 — Auto-crítica e Reflexão OBRIGATÓRIA (falhou 2x)

Antes de CADA movimento: duplicatas verificadas? Repo alvo correto? Ajudando de verdade?
Pausar 5s e refletir antes de executar. O usuário EXIGE auto-crítica constante.

## Regra #1 — VERIFICAR duplicatas ANTES e contar PRs corretamente (C-R-Í-T-I-C-O)

**CRITICAL: falhou 2x em sessões passadas. Regra absoluta.**

### Contagem precisa de PRs

⚠️ `gh search prs` usa a Search API com default **per_page=30** — retorna no máximo 30
resultados, mesmo que haja mais PRs. O count real pode ser maior.

```bash
# ❌ PODE SUBESTIMAR — default 30 resultados
gh search prs --repo NousResearch/hermes-agent --author wesleysimplicio --state open --json number --jq 'length'

# ✅ CORRETO — gh pr list não tem esse limite
gh pr list --repo NousResearch/hermes-agent --author wesleysimplicio --state open --limit 50 --json number --jq 'length'
```

### Verificar duplicatas antes de criar PR

```bash
gh search prs --repo NousResearch/hermes-agent --author wesleysimplicio "<titulo>" --json number --jq '.[0].number'
gh api "repos/NousResearch/hermes-agent/pulls?state=open" --jq '.[] | "\(.number): \(.title)"'
```

No script `zero_pr_factory.sh`, a função `criar_pr()` JÁ TEM guarda de duplicata:
```bash
local existente=$(gh search prs --repo NousResearch/hermes-agent --author wesleysimplicio "$titulo" --json number --jq '.[0].number')
if [ -n "$existente" ] && [ "$existente" != "null" ]; then
    echo "DUPLICATA: PR #$existente já existe"
    return
fi
```
Confiar no script. Verificar MANUALMENTE antes de criar PRs por agente LLM.

## Regra #2 — Prioridade: salvage > review > fix > docs > chore > refactor

Salvage e review têm PRIORIDADE sobre criar PRs novas.

## Regra #3 — Fork remote workflow

Quando o repo tem dois remotes (`origin` = upstream read-only, `fork` = seu fork):

```bash
# 1. Branch no clone local (em main atualizado)
git checkout main && git pull --ff-only origin main
git checkout -b simplicio/fix-<issue-number>-descricao-kebab-case

# 2. Push para o fork
git push fork simplicio/fix-<issue-number>-descricao-kebab-case

# 3. Criar PR apontando para o upstream (--repo obrigatório)
gh pr create --repo NousResearch/hermes-agent \
  --head wesleysimplicio:simplicio/fix-<issue-number>-descricao \
  --base main \
  --title "fix(escopo): descrição curta" \
  --body "Closes #<issue-number>

<detalhes do que mudou>"
```

A flag `--head wesleysimplicio:branch` é OBRIGATÓRIA — sem ela o gh tenta
criar a PR de `origin:branch` (que não existe, pois origin é read-only).

## Regra #4 — Salvage: só PRs <2 semanas

PR >3 meses = conflitos massivos. Comprovado. NÃO TENTAR.

## Regra #5 — Review PRs de outros antes de criar novas

Usar template: pontos fortes, pontos a melhorar, conflitos, veredito.

## Regra #6 — Pipeline 0 Tokens: zero_pr_factory.sh

```bash
# /Users/wesleysimplicio/Projetos/ai/hermes-agent/zero_pr_factory.sh
bash zero_pr_factory.sh noqa  # 5-15 PRs, 0 tokens
```

## Regra #7 — Noqa RUF100 é o filler mais rápido

`ruff check --select RUF100 --fix <dir>` → 1 PR por diretório. Validado: 20+ PRs.

## Regra #8 — Conventional Commits

`fix(escopo): descrição`. Escopos: cli, gateway, agent, tools, plugins, docs.

## Regra #9 — Padrões Validados

- `len(x)==0` → `not x`
- `f"{var}"` → `var` (se string)
- Unused imports removal
- Docs fixes (sempre verificar i18n zh-Hans)
- Noqa RUF100 cleanup

## Regra #10 — Foco: UM repo por sessão

Só Hermes Agent oficial. Dispersão = perda de tempo comprovada.

## Regra #11 — NUNCA FAZER (violado 3x nesta sessão)

- ❌ PR duplicata (violado 2x: #58885 duplicou #58877, script criou 5 dups)
- ❌ PR em fork — sempre `--repo NousResearch/hermes-agent` (violado: 7 PRs no fork)
- ❌ Dispersão em múltiplos repos (violado: simplicio + Asolaria + N-Nest-Prime)
- ❌ Salvage 3+ meses — conflitos massivos, inviável
- ❌ Crons de monitoramento frequente (1min, 5min) — usuário mandou parar
- ❌ Mixed concerns numa PR
- ❌ Sem py_compile antes de criar PR
- ❌ Commit message em português

## Regra #12 — Token Economy

| Modo | Tokens/PR |
|------|-----------|
| Agente LLM | ~500 |
| Script shell | **~0** |
| Manual | ~5.000 |

## Regra #13 — Issue Orphan Detection (quando COUNT < 10 ou buscar novas)

Quando o número de PRs abertas estiver baixo, ou quiser encontrar novas issues
para PRs rápidas, use o pipeline de detecção de orphan:

1. **Buscar issues candidatas:**
   ```bash
   gh api "repos/NousResearch/hermes-agent/issues?state=open&labels=type/bug,type/docs&sort=created&direction=desc&per_page=10" --jq '.[] | select(.pull_request == null) | [.number,.title,.created_at[0:10]] | @tsv'
   ```

2. **Verificar se é orphan real (sem PR vinculado):**
   ```bash
   gh api "repos/NousResearch/hermes-agent/issues/<N>/timeline" --jq '[.[] | select(.source and .source.issue and .source.issue.pull_request) | .source.issue.number]'
   ```
   Array vazio `[]` = orphan verdadeiro ✅. Se não-vazio, a issue já tem PR vinculado.

3. **Localizar código-fonte:**
   - `find /repo -maxdepth 4 -name "*.css"` para issues visuais
   - `gh search repos --owner NousResearch` para descobrir se o site é outro repo
   - Ler o arquivo relevante para avaliar complexidade

4. **Avaliar complexidade:**
   - **Mecânico** (noqa, typo, config) → PR direto
   - **Design** (cores, layout) → PR com before/after, pode precisar input humano
   - **Arquitetural** → flag para sessão futura

## Regra #14 — Batch PR Creation via Parallel Delegation

Para criar múltiplos PRs rapidamente (>3 PRs/sessão):

1. **Scan issues**: Buscar issues recentes sem PR (`select(.pull_request == null)`)
2. **Triagem rápida**: Priorizar issues com `proposed fix` claro no body (1-5 linhas de diff)
3. **Delegar fixes simples**: Usar `delegate_task` para issues ultra-simples (regex, label rename, one-liner guard)
4. **Fazer diretamente**: Issues de média complexidade (middleware ordering, config propagation) fazer você mesmo
5. **Pular complexas**: Issues que exigem mudanças arquiteturais ou novo código — flag para sessão dedicada

Exemplo de delegação bem-sucedida (3 PRs em paralelo esta sessão):
- WhatsApp LID regex (#59136)
- Piper TTS WAV→OGG (#58845)
- ACP model routing explicit prefix (#59089)

SEMPRE incluir workflow completo (+ git add/commit/push/PR create) no `context`
da delegação. Incluir `--repo NousResearch/hermes-agent` explícito no comando
`gh pr create`.

## Regra #15 — Lightweight Verification Before Push

SEMPRE verificar modificações em Python antes de push:

```bash
# Syntax check
py_compile.compile("caminho/do/arquivo.py", doraise=True)

# Import check (se o módulo puder ser importado standalone)
python3 -c "__import__('modulo')"
```

Para arquivos .tsx/.ts com alterações de string literal (sem lógica):
verificação opcional — o risco é mínimo.

## Regra #16b — RED CI ≠ Código Quebrado (diagnosticar antes de "fixar")

PR com TODOS os checks vermelhos raramente é defeito de código. Antes de gastar
ciclos "corrigindo CI", distinguir bloqueio de CI em nível de CONTA (jobs nem
iniciam) de falha real. Receita completa + tabela de decisão:
`references/ci-blocked-vs-broken.md`.

Caminho rápido:

```bash
# 1. Os jobs rodaram ou a conta está bloqueada?
gh run view <RUN_ID> --repo <o>/<r>            # procura "account locked due to a billing issue"
gh run view <RUN_ID> --log                      # vazio => nada executou

# 2. O merge é bloqueado por esses checks?
gh api repos/<o>/<r>/branches/main/protection/required_status_checks   # 404 => não obrigatório
gh pr view <N> --repo <o>/<r> --json mergeable,mergeStateStatus        # MERGEABLE => seguro mergear

# 3. Falha local é pré-existente / ruído de versão?
git diff origin/main...HEAD --name-only | grep arquivo-que-falhou     # fora do diff => pré-existente
node -v ; python3 --version                                        # version-gated (Node<18, Py<3.10)
```

Se CI está bloqueada por conta e o PR é `MERGEABLE` sem required status checks →
mergear e comentar NO PR/issue POR QUÊ os checks estão vermelhos (pra revisor não
ser enganado). NÃO "consertar CI" — não há código a consertar.

Sinais de bloqueio (não falha): todos os checks vermelhos de uma vez (inclusive
os irrelevantes p/ a mudança); `gh run view --log` vazio; annotation "account
locked due to a billing issue".

## Regra #16c — Disciplina de Fechamento: PR mergeada + Issue fechada

Entrega completa = PR MERGED **E** issue CLOSED. PR mergeada com issue aberta =
entrega PARCIAL (padrão do Wesley). Se você mergeou o PR (`gh pr merge`), feche a
issue explicitamente com comentário de evidência: SHA do merge commit, o que foi
preservado (invariantes), e — se CI vermelho — o MOTIVO (ex.: lock de billing de
conta, não código). Isso impede reabertura de "PR quebrada" que estava ok.

```bash
gh pr merge <N> --merge --delete-branch=false
gh issue close <ISSUE> --repo <o>/<r> --comment "Resolvida pelo merge da PR #<N> (commit <sha>).
<o que mudou>. CI checks vermelhos por lock de billing da conta, não por código; ruído
pré-existente documentado."
```

## Regra #16 — Issue Triage para PRs Rápidas

Quando precisar de muitas PRs rápidas:

1. **Scan issues recentes** (últimas 48h):
   ```bash
   gh api "repos/NousResearch/hermes-agent/issues?state=open&sort=created&direction=desc&per_page=30" \
     --jq '.[] | select(.pull_request == null and .user.login != "wesleysimplicio") | [.number,.title,.user.login,.created_at] | @tsv'
   ```

2. **Check proposed fix**: Ler o body (`gh issue view <N> --json body`). Se tiver
   um diff claro e testado → PR direto sem investigação extra.

3. **Prioritize issues with labels** `type/bug` (mais prováveis de merge rápido).
   Issues sem labels são candidatos mais fracos.

4. **Complexity sizing**:
   - *Ultra-fast* (<60s): string rename, regex add, one-line guard — delegar
   - *Fast* (2-5min): middleware order, config propagation — fazer direto
   - *Medium* (5-15min): requires understanding code flow — fazer direto se urgente
   - *Complex* (>15min): arquitetural, multi-file — flag para outra sessão

5. **Verification do proposed fix**: Se a issue já tem o diff testado, confie e
   aplique. Se não tiver, verifique com `py_compile` antes do commit.

Detalhes e exemplos: `references/session-20260705c-batch-pr-farming.md`.
