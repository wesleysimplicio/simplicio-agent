# Checkpoint and restore points

Use this when the user asks to preserve current work immediately, especially across multiple Simplicio repositories.

## Safe sequence

```bash
stamp=$(date -u +%Y%m%d-%H%M%S)
git status --short --branch
git diff --stat
git ls-files --others --exclude-standard

git switch -c checkpoint/<repo>-$stamp
git add <explicit-source-files>
git diff --cached --name-only
git commit -m "chore(checkpoint): preserve <repo> state $stamp"
git push -u origin checkpoint/<repo>-$stamp
git tag -a restore-<repo>-$stamp -m "Restore point for <repo> at $stamp"
git push origin restore-<repo>-$stamp
```

## Evidence gate

Verify all three handles after pushing:

- local commit SHA;
- remote branch SHA;
- remote restore tag resolution.

A PR may be opened from the checkpoint branch, but checkpoint, PR-open, and merged are distinct states. If tests are deferred by the maintainer, put that fact in the PR body and final report. Do not use `git add .`: runtime execution commonly creates `.simplicio/*`, `.orchestrator/*`, ledgers, journals, caches, and build output that are not source deliverables.

## Recovery semantics

To restore source, check out the tagged commit or branch. Generated runtime artifacts intentionally excluded from the commit are not part of the source restore point and must be regenerated or restored separately if needed.
