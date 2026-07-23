#!/usr/bin/env bash
# Master script: Cria todas as 12 issues de melhoria do Simplicio
# Uso: bash ~/.simplicio_agent/skills/fix-enforcement/scripts/run-all-issues.sh [repo-slug]
set -euo pipefail

REPO="${1:-wesleysimplicio/simplicio-runtime}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo "Criando 12 issues de melhoria no $REPO"
echo "Data: $(date '+%Y-%m-%d %H:%M')"
echo "=============================================="
echo ""

if ! command -v gh &>/dev/null; then
    echo "gh CLI nao encontrado. Instale com: brew install gh"
    exit 1
fi

if ! gh auth status &>/dev/null; then
    echo "gh nao autenticado. Rode: gh auth login"
    exit 1
fi

if ! gh repo view "$REPO" &>/dev/null; then
    echo "Repositorio $REPO nao encontrado ou sem acesso"
    exit 1
fi

echo "Repo $REPO encontrado"
echo ""

ISSUES=(
    "01-modularizar"
    "02-testes"
    "03-agent-ipc"
    "04-cicd"
    "05-selfhealing"
    "06-feature-flags"
    "08-observabilidade"
    "09-aprendizado"
    "10-llm"
    "11-codigo-morto"
    "12-skills-markdown"
    "13-hermes-parity"
)

TOTAL=${#ISSUES[@]}
SUCCESS=0
FAIL=0

for issue in "${ISSUES[@]}"; do
    SCRIPT="$SCRIPT_DIR/create-issue-$issue.sh"
    if [ ! -f "$SCRIPT" ]; then
        echo "Script nao encontrado: $SCRIPT (pulando)"
        FAIL=$((FAIL + 1))
        continue
    fi
    echo "--- Criando issue $issue ---"
    if bash "$SCRIPT" "$REPO"; then
        echo "OK"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "FALHOU"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "Resumo: $SUCCESS/$TOTAL criadas, $FAIL falhas"
echo "Comando manual se algo falhar: bash $SCRIPT_DIR/create-issue-NNN.sh $REPO"
