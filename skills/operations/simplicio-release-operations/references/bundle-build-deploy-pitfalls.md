# Bundle Build + Deploy — Pitfalls & Recipes

Observed while rebuilding the `.simplicio_agent` immutable bundle from
`wesleysimplicio/simplicio-agent` main and promoting it live.

## Build the bundle (immutable, versioned)
```bash
cd /Users/wesleysimplicio/Projetos/ai/simplicio-agent
export SIMPLICIO_AGENT_HOME=/Users/wesleysimplicio/.simplicio_agent
export SIMPLICIO_RUNTIME_REPO=/Users/wesleysimplicio/Projetos/ai/simplicio-runtime
bash tools/build_bundle.sh --ref origin/main
# -> creates releases/v0.25.0-<hash>, verifies, atomic-promotes `current`
```
- The script refuses to overwrite an existing `releases/<version>` → if you
  rebuilt the same ref, bump or delete the stale release dir first.
- It copies the kernel from `~/.local/bin/simplicio` or
  `$SIMPLICIO_RUNTIME_REPO/target/release/simplicio` (must exist or build fails).
- `atomic_promote` repoints the `current` symlink ONLY. The live gateway
  process keeps its OLD venv open in memory until it is restarted.

## Post-build test in the NEW bundle's venv
The bundle venv has no `pytest` (the `[fast]` extra is runtime-only).
The venv `pip` shebang is BROKEN (points at the deleted staging dir):
```bash
NB=~/.simplicio_agent/releases/v0.25.0-<hash>
cd "$NB/code"
"$NB/venv/bin/python" -m pip install --quiet pytest   # use python -m pip, NOT venv/bin/pip
"$NB/venv/bin/python" -m pytest -q tests/...
```
- `"$NB/venv/bin/python"` works (correct shebang); `"$NB/venv/bin/pip"` fails
  with `bad interpreter`. Always go through `python -m pip`.
- This does not touch the running bot (it imports, never invokes pip).

## Verify which bundle the LIVE bot is running
```bash
GW=$(pgrep -f "hermes_cli.main gateway run --replace" | head -1)
lsof -p "$GW" 2>/dev/null | grep -E "releases/" | head -1
# -> shows e.g. .../releases/v0.25.0-fast/venv/...  (the OLD one if not restarted)
readlink ~/.simplicio_agent/current   # the NEW one, after promote
```
If `lsof` shows the old `releases/<old>` while `current` points at the new,
the bot has NOT picked up the new bundle yet.

## Restart the live bot — BLOCKED from inside the gateway
- `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway-simplicio-agent`
  is INTERCEPTED when run from the same session/host context that hosts the
  gateway: the gateway kills the command via SIGTERM propagation before it
  completes ("cannot restart or stop the gateway from inside the gateway process").
- Canonical path: the USER issues `/restart` in the Simplicio Discord.
  The plist has `KeepAlive=true`, so after the kill it respawns from the new
  `current` symlink on its own.
- Agent (no Discord API access) CANNOT perform this step — leave it to the user.
- Do NOT try to `launchctl unload/load` either; same block applies.

## Reporting contract
After a rebuild + promote, do NOT say "deployed" until:
1. `current` → new release, AND
2. the live PID's `lsof` shows the new release (requires user `/restart`), AND
3. (ideally) `gateway.log` shows the new bundle booting.
Until step 2, state explicitly: "bundle built + promoted; bot still on old
release pending /restart".
