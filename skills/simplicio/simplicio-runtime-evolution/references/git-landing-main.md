# Landing Simplicio evolution on `main` (verified 2026-07-08)

Proven sequence. Repos: `simplicio-agent` (source of truth) + `simplicio-runtime` (mirror under `skills/<cat>/`). Both push to `main`.

## Pre-flight
- Confirm MCP live: `hermes mcp list` → `simplicio ✓ enabled`.
- Snapshot state: `git status -s`, `git log --oneline -3`, `git remote -v`, `git branch -vv` in EACH repo.

## Make + verify (already done before this step)
- Change via `simplicio edit --plan plan.json` (managed repo) or `mcp_simplicio_edit`.
- Test via `simplicio shell -- python3 -m pytest <path> -q` (NOT `mcp_simplicio_test_run` — it binds `repo` to the wrong cwd → "No such file or directory").

## Land on main (per repo)
```bash
# 1. preserve others' uncommitted dirt (never -f checkout / reset)
git stash push -m "wip-pre-main-$(date +%s)"

# 2. jump to main from origin/main (avoids carrying local unmerged dirt)
git checkout main                       # may fail if a /tmp worktree holds main — see trap
git merge --no-ff <feature-branch> -m "feat(...): merge X to main"

# 3. if push rejected (other bot advanced origin/main): rebase then push
git pull --rebase origin main
git push origin main

# 4. restore dirt
git stash pop                           # on JSONL-log conflict: union both sides, drop markers
```

## Pitfalls (hit this session)
- **Worktree trap (runtime).** `/private/tmp/simplicio-runtime-mywork` often holds `main` → `git checkout main` fails: "already used by worktree at /private/tmp/...". Fix:
  `git worktree remove --force /private/tmp/simplicio-runtime-mywork` (only when clean / on origin/main), then retry. Also clear `/private/tmp/simplicio-runtime-isolation-test` the same way.
- **origin/main advanced.** Non-fast-forward push → `git pull --rebase origin main` before push.
- **Stash-pop conflict on append-only logs** (e.g. `.orchestrator/learn/pending.jsonl`). Resolve by UNION (keep both sides' lines, delete `<<<<<<<` / `=======` / `>>>>>>>` markers) — it is just a log, never overwrite.
- **MCP `test_run` wrong cwd.** Use `simplicio shell -- <cmd>` from the correct dir.
- **MCP `edit` inline JSON.** Pass plan as inline JSON; or drop to CLI `simplicio edit --plan <file.json>` with `{"op":"create","text":"..."}` for new files in a managed repo.
- **Alien files in MY working tree (concurrent bots).** `git status -s` may reveal modified files you never touched (other bot wrote to the same checkout, e.g. `cli.py`, `hermes_cli/banner.py`). They are NOT part of your change. Do not `git add -A`. Isolate before rebase/push:
  ```bash
  git stash push cli.py hermes_cli/banner.py -m "wip-alien-<other-bot>"
  git pull --rebase origin main     # remote advanced w/ other bot's work
  git push origin main              # now accepted
  git stash pop                     # restore their dirt untouched
  ```
  If `git status` shows `0 0` vs origin after push, your commit landed and theirs is untouched. Verify with `git rev-list --left-right --count origin/main...HEAD` → `0 0`.

## Gap detection → next evolution
`simplicio doctor --json` (via `mcp_simplicio_exec command="doctor --json"`). Read `compatibility[].status`:
- `"incompatible"` adapter (e.g. `simplicio-prompt` missing envelope cache keys) → bump/fix adapter.
- Installed binary missing a source subcommand (e.g. `wormhole` exists as `wormhole_command` in runtime source but `simplicio` v3.4.0 doesn't expose it) → rebuild binary from current runtime source, don't re-implement in Python.
