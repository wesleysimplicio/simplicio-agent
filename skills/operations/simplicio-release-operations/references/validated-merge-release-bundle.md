# Validated merge → release → bundle pattern

Reusable evidence from the 2026-07-12 Simplicio Agent deployment workflow.

## Repository/runtime separation

- Source: `/Users/wesleysimplicio/Projetos/ai/simplicio-agent`
- Runtime state/bundles: `/Users/wesleysimplicio/.simplicio_agent`
- The Hermes original home is separate and must not receive Simplicio changes.

## Safe publication sequence

1. Validate the integrated candidate in an isolated worktree and keep unrelated untracked checkout files out of the branch.
2. Record the active bundle before changing `current`: capture `build-info.json`, resolved release path, commit, and rollback command in a restore-point JSON; preserve the old release and add a restore tag if a durable remote source point is wanted.
3. Push a publication branch and create the PR. Query the PR API directly: `mergeable=true` and `mergeable_state=clean` are the relevant merge gates. `gh pr checks` may say no checks were reported; do not rewrite that as “checks passed.”
4. After merge, fetch `origin/main` and update a local main checkout with `git merge --ff-only origin/main`. Do not use `git reset --ff-only` (that option does not exist).
5. Create and verify the version tag/release only after the merged SHA is known.

## Bundle verification checklist

Run the official `tools/build_bundle.sh` dry run, then the real build. Verify all of:

- `current` resolves to the intended versioned release;
- `build-info.json.commit` equals the merged `main` SHA;
- release has `code/`, `venv/`, `build-info.json`, and `kernel/simplicio` when the runtime binary is available;
- `code/.git` is absent;
- imports from the bundle venv resolve under the new release, not the source checkout;
- kernel `--version` responds;
- old release and restore-point JSON/symlink still exist.

## Gateway state distinction

Changing `current` and `.active_bundle` does not reload an already-running gateway. Verify launchd label, PID, and process age separately. Do not unload/reload or kill the gateway as an implicit side effect. If activation is required, use the approved `/restart` path or obtain explicit restart authorization, then verify the new process and bundle. Report clearly when the pointer is new but the live process is still old.
