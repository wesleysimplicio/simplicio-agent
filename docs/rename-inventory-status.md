# Rename inventory — status atual (issue #187)

Gerado a partir de `python3 -m tools.rename_guard.scanner --json` no commit
`8e9b63a` (branch `claude/issue-186-iiwbul`), 2026-07-13.

## Contagens

| classe            | contagem | origem                                                    |
|-------------------|---------:|------------------------------------------------------------|
| `upstream`        |   21,922 | allowlist `archive/*` (fork pré-existente, não distribuído) |
| `KEEP_INTERNAL`   |   17,535 | allowlist `hermes_cli/*`, `tests/hermes_cli/*`              |
| `credit`          |       42 | allowlist `CHANGELOG.md`                                    |
| `baseline` (sem classe da taxonomia #186) | 30,073 | congelado em `tools/rename_guard/baseline.json`, ainda não revisado |
| **total**         | **69,572** |                                                            |
| `new` (regressão) |        0 | guard passa limpo                                           |

O `rename-guard` (issue #194, mergeado em `8e9b63a`) já impede que **novas**
ocorrências entrem sem allowlist/baseline — isso está funcionando. O que
falta para fechar #187 é a classificação real das 30.073 ocorrências que
hoje só têm o rótulo operacional `baseline` (= "dívida pré-existente, não é
regressão"), que **não** é uma classe da taxonomia da épica (`RENAME_PUBLIC`,
`MOVE_WITH_SHIM`, `DEPRECATE_ALIAS`, `MIGRATE_STATE`, `KEEP_INTERNAL`,
`KEEP_UPSTREAM_REFERENCE`, `DELETE_OBSOLETE`, `GENERATED_REBUILD`,
`THIRD_PARTY_OR_LICENSE_KEEP`). Isso viola o critério de aceite "Public
occurrences não podem ficar UNCLASSIFIED."

## Distribuição por diretório/arquivo (30.073 não classificadas)

Maiores concentrações — provável ordem de trabalho por owner de superfície:

| ocorrências | local            | superfície provável (épica #186) |
|------------:|------------------|-----------------------------------|
| 13,144 | `tests/`             | fixtures/histórico — revisar caso a caso, provável `historical-fixture` |
| 3,743  | `desktop/`           | superfície pública (#188) — candidato a `RENAME_PUBLIC` |
| 2,468  | `plugins/`           | superfície pública (#188/#191) |
| 1,499  | `tools/`             | inclui o próprio rename-guard e utilitários internos |
| 1,254  | `agent/`             | núcleo — misto de símbolos internos e strings públicas |
| 981    | `optional-skills/`   | skills distribuídas (#189) |
| 960    | `gateway/`           | superfície pública (#188) |
| 772    | `scripts/`           | maioria interna, revisar |
| 695    | `skills/`            | skills distribuídas (#189) |
| 425    | `nix/`               | packaging (#118/#127) |
| 381    | `ui-tui/`            | superfície pública (#188) |
| 348    | `apps/`              | superfície pública |
| 326    | `cli.py`             | CLI pública (#188) — alta prioridade |
| 314    | `docker/`            | distribuição (#118) |
| 302    | `docs/`              | docs públicas (#189) |
| 296    | `tui_gateway/`       | superfície pública (#188) |
| 194    | `acp_adapter/`       | protocolo (#191) |
| 192    | `locales/`           | locales (#192) |
| 172    | `AGENTS.md`          | doc pública raiz |
| 153    | `hermes_constants.py`| provável `HERMES_*` interno — revisar contrato |
| ...    | (mais 68 arquivos/diretórios, ver relatório completo) |

Relatório completo (69.572 ocorrências, path+line+term+class+reason) pode
ser regenerado com:

```
python3 -m tools.rename_guard.scanner --json
```

## O que este pass NÃO cobre (fora do escopo desta sessão)

Conforme #187 pede fontes além do source tree — não executado aqui:

- wheel/sdist build + inspeção de `METADATA`/`RECORD`/entrypoints
- build standalone/native e desempacotamento
- build do Desktop (Electron) e inspeção de app bundle/asar/resources
- export de layers de imagem Docker
- build/scan de outputs de site/docs gerados
- OCR de screenshots/assets

Essas exigem builds reais dos artefatos distribuídos e devem ser tratadas
como um passo separado (possivelmente já coberto por #194/#195) antes de
#187 poder ser fechada com a evidência completa exigida pela épica.

## Próximo passo recomendado

Revisar as 30.073 ocorrências `baseline` por diretório (tabela acima),
atribuindo classe da taxonomia + owner + expiry em
`tools/rename_guard/allowlist.json`, começando pelas superfícies públicas
de maior contagem (`desktop/`, `plugins/`, `cli.py`, `gateway/`,
`ui-tui/`, `tui_gateway/`) antes das internas (`tests/`, `scripts/`,
`tools/`).
