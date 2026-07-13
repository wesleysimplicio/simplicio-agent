# Git Local-Branch Trap & `simplicio edit --repo` Pitfall (learned 2026-07-11)

## Problem 1 — working tree on a stale feature branch, not `main`
The canonical checkout at `~/Projetos/ai/simplicio-runtime` was on branch
`issue/3050`, NOT `main`. Every `git commit` there lands on `issue/3050`,
invisible to `origin/main` until carried over. The standing directive is
"commit and push to main", so a commit on `issue/3050` is not enough.

### Verified recipe (what actually worked this session)
```bash
cd ~/Projetos/ai/simplicio-runtime
git add <explicit files>                 # never -A / never .
git commit -m "..."                      # lands on issue/3050  -> sha ABC123
git checkout main                         # switch to main
git cherry-pick ABC123                   # apply same change on main
git push origin main                      # main advances (confirmed by git)
git checkout issue/3050                  # restore working branch, NO loss
```
- Confirm before push: `git log --oneline -2 origin/main` shows the new sha.
- Restoring the working branch preserves pre-existing alien/third-party
  modifications in its tree (e.g. `Cargo.lock`, `doctor.rs`,
  `hermes_parity_capabilities_ext.rs`) — they stay untouched and uncommitted.
- This pattern is distinct from the worktree trap / origin-advanced rebase
  covered in `git-landing-main.md`: here the LOCAL checkout itself is on a
  non-main branch, so the commit is structurally on the wrong branch even
  before any remote conflict.

## Problem 2 — `simplicio edit` validates against the WRONG repo
When run from the runtime dir WITHOUT `--repo .`, the watcher/verification step
reported `simplicio validate --repo .../simplicio-agent -> PASS` — it validated
the OTHER repo. The edit applied to the correct file (relative path resolved
against cwd), but the validation target was wrong, which can hide a real
failure in the repo you meant to change.

### Rule
ALWAYS pass `--repo .` to `simplicio edit` (and `validate`, `run`, `memory`,
`runtime map`) when operating inside a managed repo, even when cwd is already
the repo root. Removes ambiguity about which repo is the target.

## Problem 3 — never delete/touch files you didn't create
Standing directive (2026-07-11): "não exclua nada que não seja seu".
The runtime working tree contained pre-existing modifications by other
tooling/bots. These were LEFT in the tree, staged explicitly ONLY for my own
files, and never committed or deleted. `git diff --stat` after commit showed
exactly my 2 files.

### Rule
- `git status --short` before add -> know what's yours vs alien.
- `git add <file1> <file2>` (explicit) — never `git add -A` / `git add .`.
- If a broad add captured alien files, `git reset --hard <parent>` and
  re-apply only your edits (see `commit-scope-containment.md`).
