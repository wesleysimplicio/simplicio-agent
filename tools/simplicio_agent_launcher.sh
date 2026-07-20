#!/usr/bin/env bash
# Simplicio Agent launcher used by the underscore-compatible `simplicio_agent`
# command.
#
# The underscore command is the bot control surface, not the interactive chat
# surface.  With no arguments it starts the supervised Simplicio bot gateway;
# it must never fall through to the agent chat default (which may be a TUI).
# Use `simplicio_agent chat` or `simplicio_agent --tui` when an interactive
# session is explicitly wanted.
set -euo pipefail

export HERMES_HOME="${HERMES_HOME:-${SIMPLICIO_AGENT_HOME:-$HOME/.simplicio_agent}}"
export SIMPLICIO_AGENT_HOME="${SIMPLICIO_AGENT_HOME:-$HERMES_HOME}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SIMPLICIO_AGENT_REPO:-$(cd "$SCRIPT_DIR/.." && pwd)}"
if [[ ! -x "$REPO_ROOT/tools/build_bundle.sh" && -x "/Users/wesleysimplicio/Projetos/ai/simplicio-agent/tools/build_bundle.sh" ]]; then
  REPO_ROOT="/Users/wesleysimplicio/Projetos/ai/simplicio-agent"
fi

BUNDLE_PY="${SIMPLICIO_AGENT_BUNDLE_PY:-$SIMPLICIO_AGENT_HOME/current/venv/bin/python}"

run_cli() {
  if [[ ! -x "$BUNDLE_PY" ]]; then
    echo "bundle nao construido — rode 'simplicio_agent build'" >&2
    exit 1
  fi
  exec "$BUNDLE_PY" -m hermes_cli.main "$@"
}

case "${1:-}" in
  build|update)
    shift
    exec "$REPO_ROOT/tools/build_bundle.sh" "$@"
    ;;
  rollback)
    shift
    target="${1:-}"
    if [[ -z "$target" ]]; then
      current="$(readlink "$SIMPLICIO_AGENT_HOME/current" 2>/dev/null || true)"
      target="$(ls -dt "$SIMPLICIO_AGENT_HOME"/releases/*/ 2>/dev/null | grep -v "$current" | head -1 || true)"
      [[ -n "$target" ]] || { echo "nenhum bundle anterior para rollback" >&2; exit 1; }
    fi
    [[ -d "$target" ]] || target="$SIMPLICIO_AGENT_HOME/releases/$target"
    [[ -d "$target" ]] || { echo "bundle nao encontrado: $target" >&2; exit 1; }
    ln -sfn "$target" "$SIMPLICIO_AGENT_HOME/current"
    printf '%s\n' "$target" > "$SIMPLICIO_AGENT_HOME/.active_bundle"
    echo "rollback -> $target"
    echo "RESTART necessario: simplicio_agent restart"
    ;;
  current)
    echo "active: $(readlink "$SIMPLICIO_AGENT_HOME/current" 2>/dev/null || true)"
    [[ -f "$SIMPLICIO_AGENT_HOME/.active_bundle" ]] && cat "$SIMPLICIO_AGENT_HOME/.active_bundle"
    ;;
  "")
    # Critical behavior: no args start the bot gateway and return; they do not
    # enter `hermes_cli.main`'s interactive chat/TUI default.
    run_cli gateway start
    ;;
  bot|start)
    shift
    run_cli gateway start "$@"
    ;;
  stop|restart|status)
    action="$1"
    shift
    run_cli gateway "$action" "$@"
    ;;
  *)
    # Explicit CLI commands retain the full canonical Simplicio Agent surface.
    run_cli "$@"
    ;;
esac
