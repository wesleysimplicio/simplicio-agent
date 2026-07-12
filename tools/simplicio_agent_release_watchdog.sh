#!/usr/bin/env bash
# =============================================================================
# simplicio_agent_release_watchdog.sh — auto-sync bot home on new release tag
#
# Covers the case the local post-tag hook cannot: releases cut on the GitHub
# web UI (no local `git tag`, so the hook never fires). This watchdog polls the
# remote for the latest release tag and, when it changes, runs
# `simplicio_agent update` so the deployed bot home tracks the newest release.
#
# State is kept in ~/.simplicio_agent/.release_watchdog_state (last synced tag).
# Idempotent: if the latest tag is already synced, it does nothing.
#
# Intended to run from a cronjob (e.g. every 30 min). No LLM, no chat.
#
# Usage:
#   tools/simplicio_agent_release_watchdog.sh [--dry-run] [--force]
# =============================================================================
set -uo pipefail

REPO_ROOT="${SIMPLICIO_AGENT_REPO:-/Users/wesleysimplicio/Projetos/ai/simplicio-agent}"
HOME_DIR="${SIMPLICIO_AGENT_HOME:-${HERMES_HOME:-$HOME/.simplicio_agent}}"
STATE="$HOME_DIR/.release_watchdog_state"
UPDATE_BIN="/opt/homebrew/bin/simplicio_agent"
DRY_RUN=0
FORCE=0

for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    --force)   FORCE=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

log(){ echo "[watchdog $(date +%H:%M:%S)] $*"; }

[[ -d "$REPO_ROOT/.git" ]] || { echo "repo nao encontrado: $REPO_ROOT" >&2; exit 1; }
mkdir -p "$HOME_DIR"

# 1. Fetch remote tags
log "fetching tags from origin..."
if ! git -C "$REPO_ROOT" fetch --tags origin >/dev/null 2>&1; then
  echo "  ! git fetch falhou (credencial/rede?) — abortando esta checagem" >&2
  exit 1
fi

# 2. Latest tag by semver (highest version wins; ignores non-semver tags)
LATEST="$(git -C "$REPO_ROOT" for-each-ref --sort=-v:refname --format='%(refname:short)' refs/tags \
  | grep -E '^[vV]?[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
if [[ -z "$LATEST" ]]; then
  echo "  ! nenhum tag semver encontrado — nada a fazer" >&2
  exit 0
fi

LAST=""
[[ -f "$STATE" ]] && LAST="$(cat "$STATE" 2>/dev/null)"

if [[ "$LATEST" == "$LAST" && "$FORCE" -eq 0 ]]; then
  log "sem mudanca de tag (atual=$LATEST) — nada a sincronizar"
  exit 0
fi

log "novo release detectado: $LATEST${LAST:+(anterior: $LAST)}"

if ((DRY_RUN)); then
  echo "  [dry-run] rodaria: $UPDATE_BIN build"
else
  if "$UPDATE_BIN" build >/dev/null 2>&1; then
    echo "$LATEST" > "$STATE"
    log "✓ bundle reconstruido com $LATEST (current repointado, estado salvo)"
  else
    echo "  ! simplicio_agent build falhou — mantendo estado anterior" >&2
    exit 1
  fi
fi
