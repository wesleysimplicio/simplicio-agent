#!/usr/bin/env bash
# Build, verify, and atomically promote an immutable Agent + Runtime bundle.
set -euo pipefail

REPO_ROOT="${SIMPLICIO_AGENT_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
HOME_DIR="${SIMPLICIO_AGENT_HOME:-${HERMES_HOME:-$HOME/.simplicio_agent}}"
RELEASES="$HOME_DIR/releases"
CURRENT="$HOME_DIR/current"
MANIFEST_TOOL="$REPO_ROOT/tools/bundle_manifest.py"
DRY_RUN=0
VERSION=""
REF=""
VERIFY_ONLY=""
ROLLBACK=""

usage() { sed -n '1,28p' "$0"; }
log() { printf '[bundle %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf 'bundle: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) shift; VERSION="${1:-}";;
    --from) shift; REPO_ROOT="${1:-}";;
    --ref) shift; REF="${1:-}";;
    --dry-run) DRY_RUN=1;;
    --verify) shift; VERIFY_ONLY="${1:-}";;
    --rollback) shift; ROLLBACK="${1:-}";;
    -h|--help) usage; exit 0;;
    *) fail "unknown arg: $1";;
  esac
  shift
done

verify_bundle() { python3 "$MANIFEST_TOOL" verify "$1"; }

atomic_promote() {
  local target="$1" tmp_link="$CURRENT.tmp.$$"
  [[ -d "$target" ]] || fail "release does not exist: $target"
  verify_bundle "$target"
  [[ -x "$target/venv/bin/python" ]] || fail "release has no executable venv python"
  "$target/venv/bin/python" -c 'import hermes_cli' || fail "Agent smoke test failed"
  rm -f "$tmp_link"
  ln -s "$target" "$tmp_link"
  python3 - "$tmp_link" "$CURRENT" <<'PY'
import os
import sys
os.replace(sys.argv[1], sys.argv[2])
PY
  printf '%s\n' "$(basename "$target")" > "$HOME_DIR/.active_bundle"
  log "current -> $target (atomic promotion)"
}

if [[ -n "$VERIFY_ONLY" ]]; then
  verify_bundle "$VERIFY_ONLY"
  exit 0
fi

[[ -e "$REPO_ROOT/.git" ]] || fail "repo not found: $REPO_ROOT"
mkdir -p "$RELEASES"
if [[ -n "$ROLLBACK" ]]; then
  atomic_promote "$RELEASES/$ROLLBACK"
  exit 0
fi

if [[ -z "$VERSION" ]]; then
  VERSION="$(git -C "$REPO_ROOT" describe --tags --always 2>/dev/null || git -C "$REPO_ROOT" rev-parse --short HEAD)"
fi
DEST="$RELEASES/$VERSION"
[[ ! -e "$DEST" ]] || fail "bundle $VERSION already exists at $DEST"
SOURCE_REF="${REF:-HEAD}"
if [[ -z "$REF" ]] && git -C "$REPO_ROOT" rev-parse --verify "${VERSION}^{commit}" >/dev/null 2>&1; then SOURCE_REF="$VERSION"; fi
COMMIT="$(git -C "$REPO_ROOT" rev-parse "${SOURCE_REF}^{commit}")"

if ((DRY_RUN)); then
  printf '[dry-run] stage %s, verify manifest + smoke, atomically promote current\n' "$DEST"
  exit 0
fi

if command -v /opt/homebrew/bin/python3.11 >/dev/null 2>&1; then PYBIN=/opt/homebrew/bin/python3.11
elif command -v python3.11 >/dev/null 2>&1; then PYBIN=$(command -v python3.11)
else fail 'Python 3.11+ not found'; fi
STAGE="$(mktemp -d "$RELEASES/.${VERSION}.tmp.XXXXXX")"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

log "staging $VERSION from $COMMIT"
TMPCODE="$(mktemp -d)"
trap 'rm -rf "$TMPCODE" "$STAGE"' EXIT
git -C "$REPO_ROOT" archive --format=tar "$SOURCE_REF" | tar -x -f - -C "$TMPCODE"
rm -rf "$TMPCODE/.git" "$TMPCODE/.venv" "$TMPCODE/__pycache__" "$TMPCODE/.pytest_cache"
mv "$TMPCODE" "$STAGE/code"
"$PYBIN" -m venv "$STAGE/venv"
"$STAGE/venv/bin/pip" install --quiet --upgrade pip wheel
"$STAGE/venv/bin/pip" install --quiet "$STAGE/code[fast]"
"$STAGE/venv/bin/python" -c 'import orjson, msgspec, hermes_cli; print("Agent + fast dependencies: OK")'

RUNTIME_REPO="${SIMPLICIO_RUNTIME_REPO:-$HOME/Projetos/ai/simplicio-runtime}"
KERNEL_SRC=""
if [[ -x "$RUNTIME_REPO/target/release/simplicio" ]]; then KERNEL_SRC="$RUNTIME_REPO/target/release/simplicio"
elif [[ -x "$HOME/.local/bin/simplicio" ]]; then KERNEL_SRC="$HOME/.local/bin/simplicio"
elif command -v simplicio >/dev/null 2>&1; then KERNEL_SRC="$(command -v simplicio)"; fi
[[ -n "$KERNEL_SRC" ]] || fail 'Simplicio Runtime binary not found; refusing incomplete official bundle'
mkdir -p "$STAGE/kernel"
cp "$KERNEL_SRC" "$STAGE/kernel/simplicio"
chmod +x "$STAGE/kernel/simplicio"
"$STAGE/kernel/simplicio" --version >/dev/null || fail 'Runtime smoke test failed'

SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$REPO_ROOT" show -s --format=%ct "$COMMIT")}"
cat > "$STAGE/build-info.json" <<JSON
{
  "version": "$VERSION",
  "source_date_epoch": $SOURCE_DATE_EPOCH,
  "repo": "wesleysimplicio/simplicio-agent",
  "commit": "$COMMIT",
  "python": "$("$STAGE/venv/bin/python" --version 2>&1)",
  "runtime": "$("$STAGE/kernel/simplicio" --version 2>&1 | head -1)"
}
JSON
mkdir -p "$STAGE/manifests"
SIGNING_KEY="${SIMPLICIO_BUNDLE_SIGNING_KEY:-}"
python3 "$MANIFEST_TOOL" create "$STAGE" --version "$VERSION" --source-commit "$COMMIT" ${SIGNING_KEY:+--signing-key "$SIGNING_KEY"}
verify_bundle "$STAGE"
"$STAGE/venv/bin/python" -c 'import hermes_cli; print("bundle smoke: Agent import OK")'

mv "$STAGE" "$DEST"
STAGE=""
rm -rf "$DEST/venv"
"$PYBIN" -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --quiet --upgrade pip wheel
"$DEST/venv/bin/pip" install --quiet "$DEST/code[fast]"
"$DEST/venv/bin/python" -c 'import hermes_cli; print("bundle venv relocation: OK")'
python3 "$MANIFEST_TOOL" create "$DEST" --version "$VERSION" --source-commit "$COMMIT" ${SIGNING_KEY:+--signing-key "$SIGNING_KEY"}
verify_bundle "$DEST"
atomic_promote "$DEST"
trap - EXIT
log "bundle $VERSION ready; unsigned=${SIGNING_KEY:+no}${SIGNING_KEY:-yes} (sha256 verification enforced)"
