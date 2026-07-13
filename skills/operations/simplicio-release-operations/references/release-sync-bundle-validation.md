# Release-sync bundle validation reference

Use this as a compact checklist for local Simplicio Agent bundle sync:

1. List cron jobs and identify the exact release-sync job by name, schedule, and prompt preview. Pause only its verified `job_id`; list again and confirm `enabled=false` and `state=paused`.
2. Inspect `tools/build_bundle.sh`, `pyproject.toml`, and the active bundle venv. A base install does not imply optional performance extras are installed.
3. Install the production extra from the local package, e.g. `pip install "$DEST/code[fast]"`, and assert imports in the bundle's own Python: `import orjson, msgspec`.
4. Build from an explicit release ref (`git archive "$SOURCE_REF"`) and write the ref commit to `build-info.json`; do not label a `HEAD` archive as a remote release.
5. In the watchdog, compare the latest supported Agent tag with `current/build-info.json`; filter out unrelated upstream calendar tags and skip the build when the deployed release is equal.
6. Validate in an isolated home before repointing live `current`. Benchmark the helper separately from gateway end-to-end latency. If live `current` was not switched, state clearly that it still uses the old dependency set.

A failed install caused by `No space left on device` should be handled by removing only temporary artifacts created by the validation run, then retrying with `PIP_NO_CACHE_DIR=1`; do not remove user releases, runtimes, or caches indiscriminately.

## build_bundle.sh — promotion path and disk-headroom pitfalls

`tools/build_bundle.sh` resolves its release root from
`${SIMPLICIO_AGENT_HOME:-${HERMES_HOME:-$HOME/.simplicio_agent}}` (lines 6–7). On this
host the LaunchAgent plist leaks `HERMES_HOME=$HOME/.hermes`, so **without overriding
the env the bundle promotes to `~/.hermes/releases/` — NOT the path the Simplicio
Agent bot reads (`~/.simplicio_agent/current`)**. The bot then keeps running the old
bundle from memory even after `current` is repointed on disk, so a "rebuild" looks
done but the live bot never picks it up (it only reloads on a `/restart` from Discord,
and launchctl kickstart is blocked from inside the gateway).

**Always invoke with both vars explicit:**
```bash
SIMPLICIO_AGENT_HOME=$HOME/.simplicio_agent HERMES_HOME=$HOME/.simplicio_agent \
  bash tools/build_bundle.sh --ref origin/main
readlink $HOME/.simplicio_agent/current   # must point at the new v0.25.0-N-<commit>
```
If `current` points under `~/.hermes/...`, the build went to the wrong home — redo
with the explicit env above (the wrong-path release under `~/.hermes` can be deleted).

### Disk-full during build (observed: 100% / 221 Mi free)
The bundle stages into a temp dir AND copies the whole tree (~19k files), so a full
volume fails mid-tar (`No space left on device`, `ui-tui/...: Failed to create dir`).
Reclaim headroom before retrying (verified recipe, ~1.3 G freed on this host):
```bash
rm -rf ~/.cache/pip ~/.cache/uv            # build caches
rm -rf /private/tmp/impl-* /private/tmp/verify-pr* /private/tmp/wt-*   # stale worktrees
rm -f ~/Projetos/ai/simplicio-agent/.simplicio/symbol-index.json \
      ~/Projetos/ai/simplicio-agent/.simplicio/endpoint-inventory.json \
      ~/Projetos/ai/simplicio-agent/.simplicio/runtime-resource-map.json  # mapper artifacts (regenerable)
# remove OLD bundle releases, keep only the live `current` target + v0.25.0-fast
for d in $HOME/.simplicio_agent/releases/v0.25.0-*/; do
  base=$(basename "$d")
  [ "$base" != "$(readlink $HOME/.simplicio_agent/current | xargs basename)" ] \
    && [ "$base" != "v0.25.0-fast" ] && rm -rf "$d"
done
df -h /Users | tail -1
```
The `.simplicio` mapper JSONs are regenerable by `simplicio-mapper` and safe to drop.
Never remove user releases/runtimes indiscriminately — only stale temp + regenerable
artifacts. After freeing space, re-run the explicit-env `build_bundle.sh` above.
