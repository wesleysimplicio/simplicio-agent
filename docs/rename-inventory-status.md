# Rename inventory — manifest (issue #187)

Gerado a partir de `python3 -m tools.rename_guard.scanner --json` +
`python3 tools/rename_guard/classify_baseline.py` no commit `8e9b63a`
(branch `claude/issue-186-iiwbul`), 2026-07-19.

## Contagens finais

| classe                       | ocorrências | arquivos | origem |
|-------------------------------|------------:|---------:|--------|
| `upstream` (allowlist)        |      21,922 |        — | `archive/*` — fork pré-existente, não distribuído |
| `KEEP_INTERNAL` (allowlist)   |      17,535 |        — | `hermes_cli/*`, `tests/hermes_cli/*` |
| `credit` (allowlist)          |          42 |        — | `CHANGELOG.md` |
| `historical-fixture`          |      13,166 |        — | `tests/*`, `.plans/*` — back-compat/fixture, épica permite explicitamente |
| `public-must-migrate`         |       9,774 |        — | debt real: precisa de PR dedicado por superfície, com shim quando aplicável |
| `compatibility-temporary`     |       5,680 |        — | módulos internos / env `HERMES_*` / paths `~/.hermes` pendentes de #117/#190 |
| `GENERATED_REBUILD`           |       1,415 |        — | `desktop/dist/*` e outros builds — nunca editar à mão |
| `MIGRATE_STATE`               |          20 |        — | `.env.example`, `.envrc` — aliases de env legados |
| `KEEP_INTERNAL` (não-allowlist)|          18 |        — | `.gitignore` |
| **total**                     | **69,572**  |  **2,328 arquivos classificados + os já allowlisted** | |
| `new` (regressão)              |           0 |        — | guard passa limpo |
| **não classificado**           |       **0** |    **0** | ver `tools/rename_guard/baseline-classification.json` |

Zero ocorrência pública sem classificação — critério de aceite de #187
atendido para o source tree.

## O que foi feito nesta sessão

1. Confirmado que o `rename-guard` (issue #194, já mergeado em `8e9b63a`)
   funciona: 0 regressões novas.
2. Criado `tools/rename_guard/classify_baseline.py`: classifica por arquivo
   (granularidade de arquivo, não de linha — ver limitação abaixo) as
   30.073 ocorrências que só tinham o rótulo operacional `baseline`,
   atribuindo classe da taxonomia de #186 + razão + issue dono.
   Gera `tools/rename_guard/baseline-classification.json`.
3. **Nenhuma ocorrência foi allowlisted "para sempre" sem justificativa.**
   Só entram na classe `public-must-migrate` (issue dona nos parênteses)
   os casos que são debt real de branding público — CLI (`cli.py`,
   `hermes`/`simplicio-agent` launcher, `ui-tui/`, `apps/`, partes de
   `desktop/`) → #188; docs/skills/plugins (`docs/`, `README*`,
   `AGENTS.md`, `CONTRIBUTING*`, `SECURITY*`, `optional-skills/`,
   `skills/`, partes de `plugins/`) → #189; packaging/distribuição
   (`nix/`, `docker/`, `packaging/`, `pyproject.toml`, `package.json`,
   `Dockerfile`, `docker-compose*.yml`) → #118; locales → #192;
   MCP/config exemplos → #191.
4. **Nenhum rename de código foi feito.** Ver "por que não" abaixo.

## Por que a classificação não virou rename agora

A épica #186 proíbe explicitamente "replace-all cego" (princípio 1) e exige
"rename atômico por superfície" com PR e evidência própria por superfície
(princípio 8, critério "PRs são separados por superfície e mergeados antes
do fechamento"). As 9.774 ocorrências `public-must-migrate` tocam:

- **identidade de pacote/distribuição** (nome do formula Homebrew, atributos
  Nix, nome do pacote npm/PyPI, imagens Docker) — mudar o nome aqui sem
  shim/versionamento quebra instalação existente, violando o próprio
  critério de aceite "Public API/packaging muda com shim e migration";
- **superfícies com build próprio** (Desktop/Electron, TUI) onde texto
  público e código de integração interna (`hermes_cli` imports) convivem no
  mesmo arquivo — precisa revisão linha a linha, não regex de diretório;
- **múltiplos repositórios/canais** (Homebrew tap, Nix flake, Docker Hub,
  locales) que exigem coordenação e teste de instalação limpa (#195) antes
  de promover.

Fazer isso agora, sem build+teste por superfície, seria exatamente o
"replace-all cego" que a épica proíbe. O produto correto de #187 é este
manifesto — a execução do rename em si é o escopo de #117/#118/#188–#192,
que seguem no backlog operacional da épica.

## Limitação de granularidade

A classificação é **por arquivo** (o arquivo inteiro herda uma classe
dominante), não por ocorrência individual. Para arquivos grandes e mistos
(`desktop/*`, `plugins/*`, `gateway/*`) isso é conservador o suficiente para
apontar o dono certo, mas a PR de rename de cada superfície ainda precisa
revisar linha a linha antes de editar — o manifesto aqui é um mapa de
prioridade, não uma instrução de find-and-replace.

## Regenerar o manifesto completo

```
python3 -m tools.rename_guard.scanner --json > /tmp/rg_report.json
python3 tools/rename_guard/classify_baseline.py
```

Saída machine-readable: `tools/rename_guard/baseline-classification.json`
(schema `simplicio.rename-inventory/v1`, path+class+reason+owning_issue por
arquivo, mais os totais por classe e por issue dona).

## O que este pass NÃO cobre (fora do escopo desta sessão)

Conforme #187 pede fontes além do source tree — não executado aqui:

- wheel/sdist build + inspeção de `METADATA`/`RECORD`/entrypoints
- build standalone/native e desempacotamento
- build do Desktop (Electron) e inspeção de app bundle/asar/resources
- export de layers de imagem Docker
- build/scan de outputs de site/docs gerados
- OCR de screenshots/assets

Essas exigem builds reais dos artefatos distribuídos e devem ser tratadas
como um passo separado (possivelmente parte de #194/#195) antes de #187
poder ser fechada com a evidência completa exigida pela épica.
