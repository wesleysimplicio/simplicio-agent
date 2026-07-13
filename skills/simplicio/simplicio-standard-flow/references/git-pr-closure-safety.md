# Git PR Closure Safety (Simplicio Runtime repos)

## Safe closure flow (branch + PR, never direct main push)
```bash
git fetch origin
git checkout -b <tipo>/<curta> origin/main
# ... edit via simplicio edit, commit (pre-commit gate runs) ...
git push -u origin <branch>
simplicio shell compact -- gh pr create --base main --title "..." --body "what/how/evidence"
# merge after validation passes
```

## CRITICAL: never force-push a shared branch without ancestry check
```bash
git fetch origin   # REAL fetch — dry-run does NOT update the origin/main ref
git merge-base --is-ancestor origin/main <local-tip> && echo SAFE || echo DESTROYS_OTHERS_WORK
```
Only force-push a branch you created this session and confirmed has no foreign commits.

## Incident transcript (2026-07-10)
Sequence that nearly destroyed PR #3060 (`75edb3e6`, "modern Hopfield associative recall"):
1. Agent committed `2ea81cec` and ran `git push -u origin HEAD` → pushed DIRECT to main (violated closure gate; user later asked "Cadê pr da implementação?").
2. To "undo" and open a PR, agent ran `git push -f 43e22397:refs/heads/main`.
3. But the remote main tip was actually `75edb3e6` (another person's PR #3060), and the local `origin/main` ref was stale (didn't reflect #3060). Force-push destroyed `75edb3e6` from remote.
4. Detected via `git show --oneline 75edb3e6` + `git merge-base --is-ancestor 75edb3e6 2ea81cec` → "NO not ancestor".
5. Restored: `git push -f 75edb3e6:refs/heads/main`. No work lost, but the risk was real.

Root cause: agent trusted the stale local `origin/main` ref and skipped ancestry verification before the force operation.

## Runtime gap (record as evolution)
- No `simplicio pr open` / `simplicio publish` command exists. Agent must use `gh` via `simplicio shell` as the native path, OR implement the command in the runtime.
- A `simplicio publish` should refuse to force-push when the remote tip has commits not present locally (ancestry guard) — preventing exactly this incident.
