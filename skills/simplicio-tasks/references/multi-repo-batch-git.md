# Multi-repo batch git operations

**When to use:** The user asks to commit+push changes across MULTIPLE repos (e.g. "tudo que estiver alterado na pasta X, faz commit e push"). NOT for a single repo — use the normal Step 6 flow.

## Protocol

### 1. Survey — find all repos with changes

```bash
find /path/to/parent -name ".git" -maxdepth 3 -type d | while read gitdir; do
  repo="$(dirname "$gitdir")"
  echo "=== $(basename "$repo") ==="
  cd "$repo"
  git status --short 2>&1 | head -50
  echo "---"
done
```

For each repo with output, note:
- Branch name (`git branch --show-current`)
- Remote origin (`git remote -v`)
- Whether changes are modified (M), staged (unstaged M at column 0 vs 1), or untracked (??)

### 2. Route — branch strategy per repo

| Repo branch | User said | Action |
|---|---|---|
| `main` | "subir pra main" | Commit → push to `main` |
| `master` | "subir pra main" | Commit → push to `master`, then create `main` from `master` and push |
| Any other | "subir pra main" | Commit → push to current → open PR to merge into `main` (if protected) |

**Protected `main`** — if push is blocked, create a feature branch, push it, open a PR, and merge it (via `gh pr merge`).

### 3. Dispatch — parallel subagents

| Field | Value |
|---|---|
| Task count | 1 per repo with changes (NOT one per file) |
| Dispatch | `delegate_task` batch mode |
| Context per task | Exact repo path, current branch, remote, list of changed files, commit message |
| Key detail | Pass the ACTUAL file list so the agent doesn't re-scan |

Commit message formula:
```
chore: update <category> (<category> = docs/cli/runtime/packaging/skills/hooks based on file types)
```

### 4. Exception handling — anticipate and fix

**Protected branch** (`git push origin main` rejected):
→ Create branch `chore/update-<scope>-crates`
→ Push to it
→ `gh pr create`
→ `gh pr merge`

**Accidental large files** (binaries, build artifacts > 50MB, or thousands of generated files):
→ Check if `rust/target/`, `node_modules/`, `.next/`, `dist/`, `build/` were included
→ `git rm -r --cached <path>`
→ Add to `.gitignore`
→ Commit removal + push

**Missing target branch** (repo on `master`, no `main`):
→ `git checkout -b main`
→ `git push origin main`

**Branch divergence** (remote has commits not in local):
→ `git pull --rebase origin <branch>`
→ Then push

### 5. Verification — confirm all clean

After all subagents finish, run:
```bash
for repo in <list>; do
  cd /path/$repo && git status --short  # must be empty
done
```

### Pitfalls

- **Worktree with large binary dirs** — a `rust/target/` or `node_modules/` that was previously gitignored can be re-introduced if someone does `git add .` without a proper `.gitignore`. Always check `.gitignore` before committing untracked dirs in Rust/Node projects.
- **Protected `main`** is common in Rust projects with CI gates — always try push first, catch the rejection, and switch to PR flow.
- **`master` vs `main`** — don't assume the default branch name. Check `git branch --show-current` before choosing push target.
- **Parallel subagents** — each runs independently. If two touch the same repo (e.g. two tasks for the same project), serialize them explicitly. For one-task-per-repo, they're independent — safe to fan out.
- **Large commits** > 10K files trigger GitHub warnings. Check the file count before commit: if `git add .` would stage > 100 files, preview with `git add --dry-run . | wc -l` first.
- **User language** — commit messages and the final report should be in the user's language (pt-BR, en, etc.). Code/filenames stay in English.
