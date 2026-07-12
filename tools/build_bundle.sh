#!/usr/bin/env bash
# =============================================================================
# build_bundle.sh — produce an immutable, versioned Simplicio Agent deploy bundle
#
# Replaces the old "sync repo -> home tree" approach. Instead of symlinking the
# live home to the working repo (drift-prone, no rollback), we build a frozen
# artifact:
#
#   ~/.simplicio_agent/releases/<version>/
#       code/        -> git-archive snapshot of the repo (no .git, no junk)
#       venv/        -> isolated virtualenv with the package installed (-e)
#       build-info.json
#   ~/.simplicio_agent/current -> releases/<version>   (the live pointer)
#
# The running bot (start-*.sh) execs `current/venv/bin/python -m hermes_cli.main`
# with HERMES_HOME still pointing at ~/.simplicio_agent (state dir). Code is
# immutable per version; state lives outside the bundle.
#
# Rollback = repoint `current` to a previous releases/<version>.
#
# Usage:
#   tools/build_bundle.sh [--version v1.2.3] [--from /path/to/repo] [--dry-run]
# =============================================================================
set -uo pipefail

REPO_ROOT="${SIMPLICIO_AGENT_REPO:-/Users/wesleysimplicio/Projetos/ai/simplicio-agent}"
HOME_DIR="${SIMPLICIO_AGENT_HOME:-${HERMES_HOME:-/Users/wesleysimplicio/.simplicio_agent}}"
RELEASES="$HOME_DIR/releases"
CURRENT="$HOME_DIR/current"
DRY_RUN=0
VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) shift; VERSION="${1:-}";;
    --from)    shift; REPO_ROOT="${1:-}";;
    --dry-run) DRY_RUN=1;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
  shift
done

log(){ echo "[build $(date +%H:%M:%S)] $*"; }
[[ -d "$REPO_ROOT/.git" ]] || { echo "repo nao encontrado: $REPO_ROOT" >&2; exit 1; }
mkdir -p "$RELEASES"

# Resolve version: explicit > latest semver tag > short sha
if [[ -z "$VERSION" ]]; then
  VERSION="$(git -C "$REPO_ROOT" describe --tags --always 2>/dev/null || git -C "$REPO_ROOT" rev-parse --short HEAD)"
  [[ -z "$VERSION" ]] && VERSION="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
fi
DEST="$RELEASES/$VERSION"

# Already built?
if [[ -e "$DEST" && -e "$DEST/build-info.json" ]] && ((DRY_RUN==0)); then
  echo "  ! bundle $VERSION ja existe em $DEST — abortando (use --version diferente ou remova)"
  exit 0
fi

# Resolve a Python >=3.11 (system 3.9 is too old for the package).
# IMPORTANT: we must NOT use the repo's own venv python here, or the new venv's
# pip would inherit the repo's editable install path and break immutability.
if command -v /opt/homebrew/bin/python3.11 >/dev/null 2>&1; then
  PYBIN=/opt/homebrew/bin/python3.11
elif command -v /opt/homebrew/bin/python3.12 >/dev/null 2>&1; then
  PYBIN=/opt/homebrew/bin/python3.12
else
  PYBIN="$(command -v python3.11 python3.12 2>/dev/null | head -1)"
fi
[[ -n "$PYBIN" ]] || { echo "python >=3.11 nao encontrado" >&2; exit 1; }
echo "  usando python: $($PYBIN --version 2>&1)"

if ((DRY_RUN)); then
  echo "  [dry-run] git archive -> $DEST/code"
  echo "  [dry-run] python -m venv $DEST/venv && pip install -e $DEST/code"
  echo "  [dry-run] repoint $CURRENT -> $DEST"
  exit 0
fi

# 1. Snapshot code (no .git, no venv, no junk)
TMPCODE="$(mktemp -d)"
git -C "$REPO_ROOT" archive --format=tar HEAD | tar -x -f - -C "$TMPCODE"
# prune heavy/unneeded dirs from the deploy artifact
rm -rf "$TMPCODE/.git" "$TMPCODE/.venv" "$TMPCODE/__pycache__" "$TMPCODE/.pytest_cache" 2>/dev/null
mkdir -p "$DEST"
rm -rf "$DEST/code"
mv "$TMPCODE" "$DEST/code"
log "codigo snapshotado ($(du -sh "$DEST/code" | cut -f1))"

# 2. Isolated venv with the package installed (editable, so `import hermes_cli` works)
log "criando venv isolado com $($PYBIN --version 2>&1)..."
"$PYBIN" -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --quiet --upgrade pip wheel 2>&1 | tail -1
# Build the package FIXED into the bundle venv (not -e). This copies the code
# into site-packages so the bundle is fully self-contained and immutable.
"$DEST/venv/bin/pip" install --quiet "$DEST/code" 2>&1 | tail -3
log "venv pronto ($(du -sh "$DEST/venv" | cut -f1))"

# 3. build-info
cat > "$DEST/build-info.json" <<JSON
{
  "version": "$VERSION",
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repo": "$REPO_ROOT",
  "commit": "$(git -C "$REPO_ROOT" rev-parse HEAD)",
  "python": "$("$DEST/venv/bin/python" --version 2>&1)"
}
JSON

# 4. Repoint current (atomic)
PREV="$(readlink "$CURRENT" 2>/dev/null || true)"
ln -sfn "$DEST" "$CURRENT"
log "✓ current -> $DEST${PREV:+(anterior: $PREV)}"
echo "$VERSION" > "$HOME_DIR/.active_bundle"
log "pronto. bundle $VERSION ativo."
