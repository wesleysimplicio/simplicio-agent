# Commit scope containment — protect third-party content

## Root cause (session 2026-07-11)
A `git add -A` after a routine runtime edit captured unintended working-tree
changes and committed them as "my" change:
- `.simplicio/memory/seeds.sql`: 58,780 insertions / **1,147 deletions** of
  third-party `.claude/skills/*` rows (skills the agent never touched).
- `crates/simplicio-compression/src/behcs.rs`, `hyper_behcs.rs`: rustfmt
  reformatting triggered by `cargo build`/`cargo test` (agent never opened them).
- `.simplicio/cron-state/release-monitor.json` and dozens of other runtime
  housekeeping files (new or modified).

The user mandate is explicit: **"não exclua nada que não seja seu"**. A broad
add violates it silently.

## Why this happens
Simplicio runtime commands are NOT read-only on the working tree:
- `simplicio edit` / `validate` / `advise` / `parallelism` rewrite neural-memory
  seeds, cron-state, event/history JSONL.
- `cargo build`/`cargo test` run `rustfmt` on every crate it compiles.
- The pre-commit gate and watcher emit state files.

## Prevention (do this every time)
1. `git status --short` BEFORE any add — expect ONLY your intended files.
2. Stage explicitly: `git add <file1> <file2>` (never `-A`, never `.`).
3. `git diff --cached --name-only` → must list exactly your files.
4. Prove sensitive files untouched:
   `git diff <parent> HEAD -- .simplicio/memory/seeds.sql | wc -l` → `0`.

## Recovery (if a broad add already committed)
DO NOT `git reset --soft` — it keeps the polluted index. Sequence:
1. `git reset --hard <parent>`            # clean tree, drops bad commit locally
2. Re-apply ONLY your edits via `simplicio edit --plan <plan>.json` (deterministic)
3. `git status --short`                   # confirm exactly your files changed
4. `git add <explicit files>`             # never -A
5. `git diff --cached --name-only`        # = your files only
6. `git commit -m "..."`                  # passes pre-commit gate
7. `git push --force-with-lease origin HEAD`   # rewrite the bad remote commit

`--force-with-lease` (NOT blind `git push -f <sha>`) only succeeds if YOUR
local tip is still the remote tip — it refuses if someone else landed in
between, so it cannot destroy others' work. This is acceptable specifically to
retract YOUR OWN just-pushed commit that contained unintended scope; it is not
a license to rewrite shared history arbitrarily.

## Verification after recovery
- `git show --stat --oneline HEAD` → only your files.
- `git diff <parent> HEAD -- .simplicio/memory/seeds.sql | wc -l` → `0`.
- `cargo test --lib asolaria` → green.
