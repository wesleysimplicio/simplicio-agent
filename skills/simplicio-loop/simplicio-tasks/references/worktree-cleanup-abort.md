# Worktree lifecycle — create, isolate, abort, cleanup

Concise, tested recipe for the `git worktree` mechanics behind `simplicio-tasks`
Step 3 isolation (worktree-per-item) and Step 6 Parallel-PR mode. Every line here
was learned by hitting a failure in a 400+ issue parallel drain.

## Background shell is `sh`, not `bash`
The Hermes `terminal` background runner executes the command string through `sh`
(dash on macOS). Two consequences:
- **Arrays do NOT exist.** `ISSUES=(22 23 …)` + `for n in "${ISSUES[@]}"` fails silently.
  Use a plain space-separated string + unquoted expansion: `for n in $ISSUES; do …`.
  OR wrap the whole body in `bash -c '…'` (then arrays work).
- A bare `for n in $ISSUES; do …` DID word-split correctly in `sh`; the failures in
  the real run were branch-exists, not shell. If a loop "does nothing", suspect the
  branch already existing locally, not the shell.

## CREATE — order and the branch-exists trap
```bash
# branch does NOT exist yet → use -b
git -C "$REPO" worktree add -b "issue/$n" "$WT"

# branch ALREADY exists locally (0 ahead, from prior work) → NO -b, PATH FIRST
git -C "$REPO" worktree add "$WT" "issue/$n"
```
- **PATH FIRST, branch SECOND.** `git worktree add "$WT" "issue/$n"` is correct.
  The reverse (`git worktree add "issue/$n" "$WT"`) errors: `invalid reference:
  /path/to/worktrees/…`.
- "a branch named 'issue/47' already exists" ⇒ drop `-b` and pass the existing
  branch as the 2nd positional arg (path first). Verify it's empty first:
  `git -C "$REPO" rev-list --count "main..issue/$n"` → if `0`, safe to reuse.

## ABORT — STOP a parallel run WITHOUT leaving zombies
This is the part that cost 4 cleanup passes. Subagents (delegate_task) and background
shells that are still creating worktrees will **recreate** any worktree you delete,
so the delete must happen LAST, after everything that could recreate is dead.

1. Kill background worktree-creation processes: `pkill -f "worktree add"`
2. Stop the delegate tasks (the orchestrator's `/stop` or cancel the delegation).
3. Only now remove worktrees:
```bash
BASE=/Users/wesleysimplicio/Projetos/ai
for repo in simplicio-mapper simplicio-dev-cli simplicio-loop simplicio-runtime simplicio-agent; do
  git -C "$BASE/$repo" worktree list --porcelain 2>/dev/null \
    | grep "^worktree " | awk '{print $2}' | grep "worktrees/" \
    | while read wt; do
        git -C "$BASE/$repo" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
      done
  git -C "$BASE/$repo" worktree prune 2>/dev/null
done
# orphan dirs the git list missed (subagent recreated between passes)
find "$BASE/worktrees" -maxdepth 1 -mindepth 1 -exec rm -rf {} + 2>/dev/null
```
4. Delete the now-orphan local `issue/*` branches (created during the run, 0 ahead,
   never pushed — otherwise they linger forever):
```bash
git -C "$BASE/simplicio-runtime" branch --list "issue/*" \
  | xargs -r -n1 git -C "$BASE/simplicio-runtime" branch -D
```
5. Confirm zero: `find "$BASE/worktrees" -maxdepth 1 -mindepth 1 | wc -l` → `0`,
   and each repo `worktree list | grep -c worktrees` → `0`.

## LOST CWD
If you `rm -rf` the directory the shell is currently in, the next command fails with
`getcwd: cannot access parent directories`. Fix immediately: `cd /Users/wesleysimplicio`
(or any stable dir) before running further git commands.

## `gh issue list --json` control chars
Inline `json.loads()` of `gh issue list --json …` output via execute_code fails on
stray control characters. Write to a file first, then parse from disk:
```bash
gh issue list --repo wesleysimplicio/$repo --state open --limit 400 \
  --json number,title > "/tmp/${repo}_issues_raw.json"
# then execute_code: open(path).read() → json.loads(raw)
```
