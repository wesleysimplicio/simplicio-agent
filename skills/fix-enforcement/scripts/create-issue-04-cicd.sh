#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-wesleysimplicio/simplicio-runtime}"
ci() { gh issue create --repo "$REPO" --title "$1" --body "$2" --label "$3"; echo "---"; }

ci \
"[CI/CD] Pipeline de integração contínua e entrega contínua automatizada" \
'## Contexto

O Simplicio tem gates para commit, orientação, ação, validação e entrega... mas **não tem um CI pipeline que execute tudo automaticamente**. Cada gate é manual. Atualmente:
- `simplicio validate` existe mas nunca é chamado automaticamente
- `simplicio packages update` existe mas não wireado em pipeline
- Releases são manuais (cargo build --release + upload)

## O que precisa acontecer

1. **`simplicio ci run`** — comando que executa pipeline completo localmente:
   lint (clippy) → build (release) → test → security audit → package → sign → report

2. **GitHub Actions workflow**:
   - `ci.yml` — roda em todo push e PR
   - `release.yml` — auto-release quando merge na main
   - `nightly.yml` — build noturno com testes extended

3. **Auto-release pipeline**:
   - PR passa por todos os gates → auto-merge
   - CI passa → bump version (semver automático) → cargo build → GitHub Release → publish

## Integração com gates existentes
Commit → Pre-commit Gate → Push → CI Run → Merge → Release Gate → Auto-Release

## Critérios de sucesso
- [ ] `simplicio ci run` executa pipeline completo localmente
- [ ] GitHub Actions CI roda em todo push/PR
- [ ] Auto-release quando merge na main
- [ ] `simplicio update` funciona do GitHub Releases' \
"ci/cd,prioridade-alta,automação"
