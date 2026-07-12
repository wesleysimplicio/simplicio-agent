#!/usr/bin/env bash
# =============================================================================
# simplicio_agent_release_watchdog.sh — auto-sync bot home on new release tag
#
# Covers explicit release checks and local release hooks. It compares the latest
# remote semver tag with the deployed bundle and only builds when the release
# actually changed. A tag is passed through as --ref so the bundle contains the
# exact release commit, not whatever happens to be checked out locally.
#
# State is kept in ~/.simplicio_agent/.release_watchdog_state.
# This script is intentionally not scheduled by cron; invoke it from a release
# hook or manually when a release check is desired.
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
# 2. Latest Simplicio Agent tag by semver. Exclude upstream calendar-version
# tags such as v2026.6.19; override when the Agent moves to a new major series.
RELEASE_TAG_GLOB="${SIMPLICIO_AGENT_RELEASE_TAG_GLOB:-v0.*}"
LATEST="$(git -C "$REPO_ROOT" tag --list "$RELEASE_TAG_GLOB" --sort=-v:refname | head -1)"
if [[ -z "$LATEST" ]]; then
  echo "  ! nenhum tag de release do Agent encontrado — nada a fazer" >&2
  exit 0
fi
LAST=""
[[ -f "$STATE" ]] && LAST="$(cat "$STATE" 2>/dev/null)"
DEPLOYED=""
if [[ -f "$HOME_DIR/current/build-info.json" ]]; then
  DEPLOYED="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version", ""))' "$HOME_DIR/current/build-info.json" 2>/dev/null || true)"
fi

if [[ "$LATEST" == "$DEPLOYED" && "$FORCE" -eq 0 ]]; then
  log "sem mudanca de release (ativo=$LATEST) — nada a sincronizar"
  [[ "$LAST" == "$LATEST" ]] || printf '%s\n' "$LATEST" > "$STATE"
  exit 0
fi

log "novo release detectado: $LATEST${DEPLOYED:+(ativo anterior: $DEPLOYED)}"

if ((DRY_RUN)); then
  echo "  [dry-run] rodaria: $UPDATE_BIN build --version $LATEST --ref $LATEST"
else
  if "$UPDATE_BIN" build --version "$LATEST" --ref "$LATEST" >/dev/null 2>&1; then
    echo "$LATEST" > "$STATE"
    log "✓ bundle reconstruido com $LATEST (current repointado, estado salvo)"
  else
    echo "  ! simplicio_agent build falhou — mantendo estado anterior" >&2
    exit 1
  fi
fi
