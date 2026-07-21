#!/usr/bin/env bash
# Simplicio Agent launcher used by the underscore-compatible `simplicio_agent`
# command.
#
# The underscore command is the interactive Simplicio Agent surface. With no
# arguments it enters the Agent CLI's normal interactive mode (including its
# TUI when configured). Bot gateway control remains available explicitly via
# `simplicio_agent bot|start|status|restart|stop`.
set -euo pipefail

# This underscore launcher is reserved for the Simplicio bot.  Do not inherit
# HERMES_HOME from another local agent (for example AlfradHD's ~/.hermes), or
# gateway start/status will target the wrong launchd service.
BOT_HOME="${SIMPLICIO_AGENT_HOME:-$HOME/.simplicio_agent}"
export SIMPLICIO_AGENT_HOME="$BOT_HOME"
export HERMES_HOME="$BOT_HOME"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SIMPLICIO_AGENT_REPO:-$(cd "$SCRIPT_DIR/.." && pwd)}"
if [[ ! -x "$REPO_ROOT/tools/build_bundle.sh" && -x "/Users/wesleysimplicio/Projetos/ai/simplicio-agent/tools/build_bundle.sh" ]]; then
  REPO_ROOT="/Users/wesleysimplicio/Projetos/ai/simplicio-agent"
fi

BUNDLE_PY="${SIMPLICIO_AGENT_BUNDLE_PY:-$SIMPLICIO_AGENT_HOME/current/venv/bin/python}"
BOT_LAUNCHD_LABEL="${SIMPLICIO_AGENT_LAUNCHD_LABEL:-ai.hermes.gateway-simplicio-agent}"
BOT_LAUNCHD_PLIST="${SIMPLICIO_AGENT_LAUNCHD_PLIST:-$HOME/Library/LaunchAgents/${BOT_LAUNCHD_LABEL}.plist}"

use_bot_launchd() {
  [[ "$(uname -s)" == "Darwin" ]] || return 1
  [[ "${SIMPLICIO_AGENT_USE_LAUNCHD:-1}" != "0" ]] || return 1
  command -v launchctl >/dev/null 2>&1
}

bot_launchd_target() {
  printf 'gui/%s/%s\n' "$(id -u)" "$BOT_LAUNCHD_LABEL"
}

bot_launchd_action() {
  local action="${1:-status}"
  local target
  target="$(bot_launchd_target)"

  case "$action" in
    start)
      if ! launchctl print "$target" >/dev/null 2>&1; then
        [[ -f "$BOT_LAUNCHD_PLIST" ]] || {
          echo "simplicio_bot: plist nao encontrado: $BOT_LAUNCHD_PLIST" >&2
          return 1
        }
        launchctl bootstrap "gui/$(id -u)" "$BOT_LAUNCHD_PLIST"
      fi
      launchctl kickstart "$target"
      echo "simplicio_bot: gateway started ($BOT_LAUNCHD_LABEL)"
      ;;
    restart)
      launchctl kickstart -k "$target"
      echo "simplicio_bot: gateway restarted ($BOT_LAUNCHD_LABEL)"
      ;;
    stop)
      launchctl kill SIGTERM "$target"
      echo "simplicio_bot: gateway stop requested ($BOT_LAUNCHD_LABEL)"
      ;;
    status)
      local details pid
      details="$(launchctl print "$target" 2>/dev/null)" || {
        echo "simplicio_bot: gateway inactive ($BOT_LAUNCHD_LABEL)"
        return 1
      }
      pid="$(printf '%s\n' "$details" | awk '$1 == "pid" && $2 == "=" {print $3; exit}')"
      if [[ -n "$pid" ]]; then
        echo "simplicio_bot: gateway active (PID $pid; $BOT_LAUNCHD_LABEL)"
      else
        echo "simplicio_bot: gateway loaded ($BOT_LAUNCHD_LABEL)"
      fi
      ;;
    *)
      echo "acao de gateway desconhecida: $action" >&2
      return 2
      ;;
  esac
}

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
    # Critical behavior: no args open the Simplicio Agent CLI/TUI. The bot
    # gateway is never started implicitly by this command.
    run_cli
    ;;
  bot|start)
    shift
    if [[ $# -gt 0 ]]; then
      run_cli gateway start "$@"
    elif use_bot_launchd; then
      bot_launchd_action start
    else
      run_cli gateway start
    fi
    ;;
  stop|restart|status)
    action="$1"
    shift
    if [[ $# -gt 0 ]]; then
      run_cli gateway "$action" "$@"
    elif use_bot_launchd; then
      bot_launchd_action "$action"
    else
      run_cli gateway "$action"
    fi
    ;;
  *)
    # Explicit CLI commands retain the full canonical Simplicio Agent surface.
    run_cli "$@"
    ;;
esac
