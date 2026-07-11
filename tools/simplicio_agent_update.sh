#!/usr/bin/env bash
# =============================================================================
# simplicio_agent_update.sh — Sync repo -> bot home (~/.simplicio_agent)
#
# Purpose:
#   Keep the running Simplicio Agent bot home in lock-step with the source
#   repo. Captures repo changes and pushes them into the deploy home so the
#   bot always runs what the repo says.
#
# What it does (idempotent, safe):
#   1. Reinstalls the repo's Python package into its venv (-e) so the binary
#      (which is a symlink to .venv/bin/simplicio-agent) reflects source.
#   2. Symlinks repo-owned paths into the home (scripts/, plugins/, adapters/)
#      WITHOUT ever deleting bot-private artifacts (memory, cache, sandboxes,
#      pairing, config.yaml, SOUL.md, profiles).
#   3. Refreshes the managed runtime kernel via runtime_manager.ensure_runtime.
#   4. Reports a proven diff of what changed.
#
# What it NEVER touches (protected):
#   memory/  cache/  sandboxes/  pairing/  bot-coordination/
#   config.yaml  SOUL.md  profiles/  image_cache/  lsp/
#
# Usage:
#   tools/simplicio_agent_update.sh [--dry-run] [--no-kernel]
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${SIMPLICIO_AGENT_HOME:-${HERMES_HOME:-$HOME/.simplicio_agent}}"
VENV="$REPO_ROOT/.venv"
DRY_RUN=0
NO_KERNEL=0

for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    --no-kernel) NO_KERNEL=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

GREEN=$'\033[0;32m'; CYAN=$'\033[0;36m'; YEL=$'\033[0;33m'; RED=$'\033[0;31m'; NC=$'\033[0m'
log(){ echo -e "${CYAN}→${NC} $*"; }
ok(){ echo -e "${GREEN}✓${NC} $*"; }
warn(){ echo -e "${YEL}⚠${NC} $*"; }
err(){ echo -e "${RED}✗${NC} $*"; }
run(){ if ((DRY_RUN)); then echo "  [dry-run] $*"; else eval "$@"; fi; }

echo "Repo : $REPO_ROOT"
echo "Home : $HOME_DIR"
echo "Venv : $VENV"
((DRY_RUN)) && warn "DRY-RUN — nenhuma mudança será aplicada"

# ---------------------------------------------------------------------------
# 0. Sanity
# ---------------------------------------------------------------------------
if [[ ! -d "$REPO_ROOT/.git" ]]; then
  err "repo root nao parece ser um git checkout: $REPO_ROOT"; exit 1
fi
mkdir -p "$HOME_DIR" || { err "nao consegui criar $HOME_DIR"; exit 1; }

# ---------------------------------------------------------------------------
# 1. Reinstall Python package into venv (-e => tracks source live)
# ---------------------------------------------------------------------------
log "Sincronizando codigo-fonte do repo no venv (pip install -e)"
if [[ ! -x "$VENV/bin/python" ]]; then
  warn "venv ausente em $VENV — criando"
  run "python3 -m venv '$VENV'"
fi
if ((DRY_RUN)); then
  echo "  [dry-run] $VENV/bin/python -m pip install -e . --quiet --no-deps"
else
  if "$VENV/bin/python" -m pip install -e . --quiet --no-deps 2>&1 | tail -3; then
    ok "venv atualizado (source do repo refletido)"
  else
    warn "pip install -e falhou — binario pode estar desatualizado"
  fi
fi

# ---------------------------------------------------------------------------
# 2. Symlink repo-owned paths into home (never delete bot-private files)
# ---------------------------------------------------------------------------
# Repo -> home path map. Only these are "owned" by the repo.
# NOTE: we deliberately do NOT symlink the repo's top-level `scripts/` into the
# home — those are dev-tools (benchmarks, ci, linters) and would collide with
# the bot's own runtime scripts (neural-recall, semantic_recall.py, etc.) that
# live in ~/.simplicio_agent/scripts and are NOT in the repo. The agent's core
# code is covered by the venv `pip install -e` step above; runtime extensions
# (plugins, adapters) are what we mirror here.
SYNC_PAIRS="plugins|plugins adapters|adapters"

for pair in $SYNC_PAIRS; do
  src_rel="${pair%%|*}"
  dst_rel="${pair##*|}"
  src="$REPO_ROOT/$src_rel"
  dst="$HOME_DIR/$dst_rel"
  [[ -d "$src" ]] || { warn "repo nao tem ./$src_rel — pulando"; continue; }
  log "Sincronizando ./$src_rel -> $dst"
  run "mkdir -p '$(dirname "$dst")'"
  # Symlink each top-level entry, never deleting extras already in dst.
  for entry in "$src"/*; do
    [[ -e "$entry" ]] || continue
    base="$(basename "$entry")"
    target="$dst/$base"
    if [[ -L "$target" ]]; then
      run "ln -sfn '$entry' '$target'"
    elif [[ -e "$target" || -d "$target" ]]; then
      # Real file/dir already in home. For code plugins/adapters this is a
      # stale copy of repo code — replace with a symlink (after backing up,
      # never deleting). User-data paths are excluded from SYNC_PAIRS so they
      # never reach here.
      if ((DRY_RUN)); then
        echo "  [dry-run] backup+symlink: $target -> $entry"
      else
        bak="$target.bak-$(date +%s)"
        mv "$target" "$bak" 2>/dev/null && log "backup: $target -> $bak"
        ln -sfn "$entry" "$target" && ok "symlink: $target -> $entry"
      fi
    else
      run "ln -sfn '$entry' '$target'"
    fi
  done
done

# ---------------------------------------------------------------------------
# 3. Runtime kernel refresh (managed dependency)
# ---------------------------------------------------------------------------
if ((NO_KERNEL)); then
  warn "pulando atualizacao do runtime kernel (--no-kernel)"
else
  log "Atualizando runtime kernel gerenciado (~/.simplicio/bin)"
  if ((DRY_RUN)); then
    echo "  [dry-run] python3 tools/runtime_manager.py ensure"
  else
    if "$VENV/bin/python" -m tools.runtime_manager ensure 2>&1 | tail -3; then
      ok "kernel verificado/atualizado"
    else
      warn "runtime_manager falhou (nao bloqueia o sync do agent)"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 4. Prove it: report diff of key paths
# ---------------------------------------------------------------------------
log "Verificacao de alinhamento (repo vs home)"
echo "  scripts no repo: $(find "$REPO_ROOT/scripts" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')"
echo "  plugins do repo (symlink no home?):"
for p in "$HOME_DIR/plugins"/*; do
  if [[ -L "$p" ]]; then echo "    $(basename "$p") -> $(readlink "$p")"; fi
done 2>/dev/null
echo "  venv python aponta pro repo? $(readlink -f "$VENV/bin/simplicio-agent" 2>/dev/null | grep -q "$REPO_ROOT" && echo SIM || echo 'NAO/ou-indireto')"
echo
ok "update concluido. Para reverter: remova os symlinks em $HOME_DIR/{scripts,plugins,adapters}."
