#!/usr/bin/env bash
# =============================================================================
# simplicio_agent_update.sh — DEPRECATED shim -> build_bundle.sh
#
# Kept for backward compatibility (old `simplicio_agent update` callers,
# post-tag hook, watchdog). The repo->home TREE-SYNC approach is replaced by
# immutable versioned bundles: `simplicio_agent build` produces
# ~/.simplicio_agent/releases/<ver>/ and repoints `current`. This shim just
# forwards to that.
# =============================================================================
set -uo pipefail
REPO_ROOT="${SIMPLICIO_AGENT_REPO:-/Users/wesleysimplicio/Projetos/ai/simplicio-agent}"
exec "$REPO_ROOT/tools/build_bundle.sh" "$@"
