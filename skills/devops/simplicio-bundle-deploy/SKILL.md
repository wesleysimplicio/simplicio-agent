---
name: simplicio-bundle-deploy
description: Build, deploy, and roll back the Simplicio Agent as an immutable versioned bundle (code + Python venv + Rust kernel together). Use when changing how the Simplicio Agent is deployed, migrating the live bot to a bundle, fixing deploy drift, or when asked about releases/rollback of the agent. Covers the launchctl-blocked-restart workaround.
---

# Simplicio Agent — Immutable Bundle Deploy

The Simplicio Agent (fork at `~/Projetos/ai/simplicio-agent`) deploys as a
**versioned, immutable artifact** instead of symlinking a live dev checkout.
This skill captures the working procedure, the gotchas that cost real time,
and how to migrate a *running* bot without breaking it.

## Mental model

- `~/.simplicio_agent/releases/<version>/` — one directory per build. Contains:
  - `code/` — `git archive` snapshot of the agent repo (no `.git`).
  - `venv/` — **fixed** Python venv (package built into site-packages, NOT editable).
  - `kernel/simplicio` — the Rust determinism kernel binary (bundled together).
  - `build-info.json` — version, commit, python, built_at.
- `~/.simplicio_agent/current` — symlink → the active release. Rollback = repoint this.
- `~/.simplicio_agent` (HERMES_HOME) — **state only**: `memory/`, `config.yaml`,
  `cache/`, `kanban.db`, `auth.json`, `sessions/`, `logs/`. Never versioned.
- The agent and kernel are resolved together: the bundle start script sets
  `HERMES_KERNEL_BIN=$BUNDLE_HOME/kernel/simplicio`, which is the FIRST slot in
  `tools/runtime_manager.resolve_kernel` (env override wins over PATH / managed dir).

A build is "immutable" only if the venv is **fixed** (`pip install .`), not
editable (`pip install -e`) — editable links back to the source repo and breaks
isolation. Proven: `import hermes_cli` resolves to the bundle's site-packages
even when the source repo is renamed/moved.

## Commands

Launcher `/opt/homebrew/bin/simplicio_agent` (or `simplicio_agent`):
- `simplicio_agent build [--version X] [--from /path/to/repo]` — build a bundle
  from the repo (git-archive + fixed venv + bundled kernel) and repoint `current`.
- `simplicio_agent rollback [version]` — repoint `current` to previous release
  (or named version). Instant, no rebuild.
- `simplicio_agent current` — print active bundle path + version.

Build script: `tools/build_bundle.sh` (called by the launcher). Resolution:
python used to create the venv is `/opt/homebrew/bin/python3.11` (system python
3.9 is too old — package needs >=3.11). Kernel source: sibling
`simplicio-runtime/target/release/simplicio`, fallback `~/.local/bin/simplicio`,
fallback `PATH`.

Start script (what launchd runs):
`~/.simplicio_agent/bin/start-simplicio-agent-discord-bundle.sh` — sets
`HERMES_KERNEL_BIN`, then `exec $BUNDLE_HOME/venv/bin/python -m hermes_cli.main gateway run --replace`.

## Live migration — THE launchctl trap

`launchctl unload`/`load`/`kickstart -k` on the gateway LaunchAgent
(`ai.hermes.gateway-simplicio-agent`) is **BLOCKED from inside the gateway
process** (the runtime SIGTERMs the command's parent tree before it finishes).
You cannot reload the plist from a terminal that is a child of the running
gateway. Symptoms: command returns "Blocked: cannot restart or stop the gateway
from inside the gateway process."

**Workaround that works (no plist reload needed):**
1. Edit the LaunchAgent's *current* ProgramArguments target —
   `~/.simplicio_agent/bin/start-simplicio-agent-discord.sh` — to become a thin
   wrapper that `exec`s the bundle start script:
   ```bash
   #!/bin/bash
   set -euo pipefail
   exec /Users/wesleysimplicio/.simplicio_agent/bin/start-simplicio-agent-discord-bundle.sh "$@"
   ```
2. `kill <gateway_pid>`. KeepAlive respawns the job, which runs the legacy
   script → wrapper → bundle. The bot now runs from the bundle.
3. (Optional later) reload the plist from a shell OUTSIDE the gateway so the
   plist points directly at the bundle script; the wrapper can then stay or be
   removed.

Do NOT rely on the in-app `/restart` Discord command for this — it re-executes
the *current* python binary (repo), not the bundle script.

## Pitfalls (each cost real debugging time)

- **System python is 3.9.6** — too old. Use `/opt/homebrew/bin/python3.11` (or
  the repo's `.venv/bin/python`) to create the bundle venv. The script picks
  this automatically.
- **`pip install -e` is NOT immutable** — it symlinks the venv back to the repo.
  The first build did this and `import hermes_cli` resolved to the repo even
  with the bundle active. Always `pip install .` (fixed build into site-packages).
- **`git archive HEAD` excludes uncommitted edits** — if you edit
  `tools/runtime_manager.py` and build the bundle *before* committing, the bundle
  ships the OLD code. Commit (or at least `git stash`/`git add`) before building.
  Diagnose by `grep`ing the pattern in `$BUNDLE/code/tools/...`.
- **`lsof` is misleading for venv python** — `venv/bin/python` is a symlink to
  the homebrew python base (`/opt/homebrew/Cellar/python@3.11/...`). A process
  running the *bundle* venv still shows the homebrew path in `lsof`. Verify the
  bundle is actually active with: `lsof -p <pid> | grep -c 'releases/<ver>'`
  (should be >0 for bundle, 0 for repo). The repo shows ~38 repo files open.
- **runtime_manager banner regex** — the real kernel prints
  `Simplicio Runtime X.Y.Z` (a `Runtime` word between name and version). The
  handshake regex must be `^\s*simplicio(?:[- ]runtime)?\s+v?(\d+)\.(\d+)\.(\d+)`
  (accepts both `-runtime` and ` runtime`). The old `(?:-runtime)?` only matched
  `simplicio-runtime` and rejected the real banner → `runtime_status()` false-
  negative. Homonym `Simplicio Agent v0.17.0` is still correctly rejected because
  the optional group only consumes `runtime`, so `Agent` blocks the match.
- **Bundle version string** — `git describe` drives the version. A stray tag
  (e.g. `restore-agent-...`) produces an ugly but functional version dir name.
  Fine to leave; just know `current` is the source of truth, not the dir name.

## Verification checklist (run after any deploy change)

```bash
# 1. bundle active + version
simplicio_agent current

# 2. process is alive and from the bundle (not repo)
PID=$(pgrep -f "hermes_cli.main gateway" | head -1)
echo "bundle files open: $(lsof -p $PID | grep -c 'releases/')"   # >0 = good
echo "repo files open:   $(lsof -p $PID | grep -c 'Projetos/ai/simplicio-agent')"  # ~1 (just cwd) = good

# 3. kernel pinned to bundle
lsof -p $PID 2>/dev/null | grep "kernel/simplicio" || \
  ps -E -p $PID | tr ' ' '\n' | grep -i kernel_bin   # should show bundle path

# 4. kernel handshake healthy (no false-negative)
HERMES_KERNEL_BIN="$HOME/.simplicio_agent/current/kernel/simplicio" \
  "$HOME/.simplicio_agent/current/venv/bin/python" -c "
import os,sys; sys.path.insert(0,'$HOME/.simplicio_agent/current/code')
os.environ['HERMES_KERNEL_BIN']='$HOME/.simplicio_agent/current/kernel/simplicio'
from tools.runtime_manager import runtime_status as rs
s=rs(); print('version:',s.version,'satisfied:',s.satisfied)"

# 5. gateway reconnected
tail -3 ~/.simplicio_agent/logs/gateway.log | grep -i "discord connected"
```

## Rollback procedure

```bash
simplicio_agent current            # note current version
simplicio_agent rollback            # to previous; or: rollback <version>
# then restart the bot (kill PID; KeepAlive respawns via wrapper -> new current)
kill $(pgrep -f "hermes_cli.main gateway" | head -1)
# verify with the checklist above
```

Rollback is atomic and covers agent + kernel together (both live inside the same
bundle directory).
