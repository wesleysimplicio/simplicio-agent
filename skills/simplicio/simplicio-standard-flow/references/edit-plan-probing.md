# Probing do schema de `simplicio edit`

Sessão-base: melhoria simultânea em `simplicio-agent` e `simplicio-runtime` guiada por Asolaria.

## Objetivo
Descobrir rapidamente o contrato aceito por `simplicio edit --plan` sem abandonar o fluxo canônico do runtime.

## Sequência validada
1. Criar plano mínimo:
   ```json
   {"schema":"simplicio.edit-plan/v1","operations":[]}
   ```
2. Rodar:
   ```bash
   simplicio edit --plan /tmp/plan.json --repo <repo>
   ```
3. Ler o erro estrutural e ajustar o shape.

## Erros observados e o que significaram
- `operations array is empty` → o schema foi reconhecido; falta operação real.
- `plan must specify a target "file"` → o plano atual é por-arquivo.
- `operation ... missing string field "op"` → cada operação precisa declarar o tipo.
- `operation ... missing required string field "find"` → replace usa ancora textual em `find`.
- `operation ... missing required string field "with"` → substituição vai em `with`, não `replace`.

## Shape confirmado
```json
{
  "schema": "simplicio.edit-plan/v1",
  "file": "/abs/path/or/repo-relative",
  "operations": [
    {
      "op": "replace",
      "find": "texto exato antigo",
      "with": "texto novo"
    }
  ]
}
```

## Uso recomendado
- usar este probing quando o comando existir mas o contrato exato não estiver fresco;
- manter a mutação via `simplicio edit`, não migrar para `patch` manual só por esquecimento de schema;
- depois de descobrir o contrato, registrar a lição na skill umbrella.

## Observação complementar
Na mesma sessão, `simplicio shell compact` ficou mais estável quando o diretório foi passado no `workdir` da chamada hospedeira e o comando real foi enviado cru após `--`, sem `cd` inline nem quoting excessivo.
