# Zero-Token Pipeline — PR Factory

## Script: `/Users/wesleysimplicio/Projetos/ai/hermes-agent/zero_pr_factory.sh`

```bash
bash zero_pr_factory.sh noqa     # noqa RUF100 cleanup (5-15 PRs)
bash zero_pr_factory.sh all      # todos os padrões
```

## Como funciona

- `grep` local para encontrar padrões (0 tokens)
- `ruff check --select RUF100 --fix` para auto-corrigir (0 tokens)
- `git` branch/commit/push (0 tokens)
- `gh pr create` com guarda de duplicata (0 tokens)

## Guarda de duplicata (CRÍTICO — falhou 2x)

O script verifica ANTES de criar:
```bash
local existente=$(gh search prs --repo NousResearch/hermes-agent --author wesleysimplicio "$titulo" --json number --jq '.[0].number')
if [ -n "$existente" ] && [ "$existente" != "null" ]; then
    echo "DUPLICATA: PR #$existente já existe"
    return
fi
```
5 duplicatas foram criadas ANTES dessa guarda ser adicionada. Ela é OBRIGATÓRIA.

## Validação (2026-07-05)

- 5 PRs criadas em uma execução: #59170-#59174 (depois fechadas como duplicatas)
- 149+ arquivos modificados
- 258 noqas removidas
- 0 tokens de LLM gastos
- ~15s por PR (vs ~2min via agente)

## Padrões implementados

| Padrão | Comando | PRs potenciais |
|--------|---------|---------------|
| Noqa RUF100 | `find . -name "*.py"` + `ruff check --select RUF100 --fix` | 5-15 |
| Wildcard imports | `grep "from.*import \*"` | 2-5 |
| len() idiom | `grep "len(" \| grep "== 0"` | 0 (esgotado) |

## Token economy

| Modo | Tokens/PR |
|------|-----------|
| Script shell (zero_pr_factory.sh) | **0** |
| Agente LLM (delegate_task) | ~500 |
| Manual (humano) | ~5.000 |
