# Auditoria de backlog em `Projetos/ai`

Use quando o usuário pedir quantas issues faltam nos projetos locais, e não apenas em um repositório já conhecido.

## Recipe seguro

1. Inventarie somente diretórios imediatos com `.git`; leia `.git/config` diretamente para extrair `remote "origin"`, evitando iniciar um processo `git` por diretório.
2. Normalize remotes HTTPS/SSH para `owner/repo` e deduplicate por repositório remoto.
3. Para cada repo, use a Search API com `is:issue is:open`, não `gh issue list --limit 500`, porque `issue list` satura em 500 e subconta repositórios maiores:

```bash
gh api -X GET search/issues \
  -f 'q=repo:OWNER/REPO is:issue is:open' \
  -f per_page=1 --jq .total_count
```

4. Reporte separadamente:
   - todos os repositórios encontrados localmente;
   - repositórios com issues abertas;
   - total incluindo upstreams externos;
   - total excluindo upstreams (por exemplo, `NousResearch/hermes-agent`).
5. Reconsulte depois de qualquer close-gate; não deduza zero a partir de PRs mergeados.

## Pitfalls

- `gh issue list --limit 500` é adequado para listar detalhes, não para contagem exata acima de 500.
- Não rode `gh` sequencialmente sobre uma árvore inteira enquanto houver `cargo build`, `simplicio-mapper scan` ou outro loop pesado: o conjunto pode provocar OOM/exit 137. Primeiro verifique processos e disco; reduza o lote ou pare somente processos claramente órfãos/da tarefa atual.
- Se o wrapper `simplicio shell` morrer antes da consulta, registre o `exit 137`, diagnostique processos/memória com uma chamada pequena e use um fallback nativo pontual somente depois do caminho Simplicio falhar por pressão do host.
- Não trate repositórios upstream como backlog do produto Simplicio sem explicitar a separação.

## Evidência

Use `MEASURED|` para cada contagem retornada pela API e inclua timestamp/consulta. Se a enumeração local ou qualquer repo não puder ser consultado, use `UNVERIFIED|` e forneça o motivo; nunca transforme um limite/truncamento em zero.