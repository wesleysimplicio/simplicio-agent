# CI Red But Not Broken — Diagnostic Recipe

When `gh pr checks` shows EVERY check failing on a PR whose diff is small/unrelated,
do NOT assume the code is broken. The most common false alarm is **account-level CI
block** (GitHub Actions disabled for the account/org, usually a billing lock). Jobs
never start — they fail at the queue, not at your code.

## Step 1 — Did the jobs even run?

```bash
gh run list --repo <o>/<r> --branch <branch> --limit 10
gh run view <RUN_ID> --repo <o>/<r>          # look for "account locked due to a billing issue"
gh run view <RUN_ID> --repo <o>/<r> --log    # empty => nothing executed
```

Tell-tale signs of a block (not a code failure):
- Every check red simultaneously, including ones unrelated to the change.
- `gh run view <RUN_ID> --log` is empty (no steps executed).
- Annotations read "account is locked due to a billing issue" / "disabled".

## Step 2 — Is merge gated by those checks?

```bash
gh api repos/<o>/<r>/branches/main/protection/required_status_checks   # 404 => not required
gh pr view <N> --repo <o>/<r> --json mergeable,mergeStateStatus        # MERGEABLE => safe to merge
```

If `mergeable: MERGEABLE` and no required status checks: you MAY merge safely.
Document in the PR/issue comment WHY CI is red (account-blocked) so reviewers
aren't misled. Do not burn cycles "fixing CI" — there is nothing to fix in code.

## Step 3 — Rule out pre-existing / environment noise (local failures)

Before attributing a local `npm run lint` / `npm test` failure to the PR:

1. Is the failing file even in the branch diff?
   ```bash
   git diff origin/main...HEAD --name-only | grep -E "failing-file"
   ```
   If NOT in the diff → pre-existing, out of scope.

2. Is the failure version/environment-specific?
   - `node -v` — `import ... with { type: "json" }` (import attributes) needs Node 18+.
   - `python3 --version` — `int.bit_count()` needs Python 3.10+; on macOS `/usr/bin/python3`
     is 3.9 and will fail even though CI's 3.10 job would pass.
   - Check for a newer local toolchain: `ls ~/.nvm/versions/node` (v18/v22 available even
     if `node` on PATH is v16).

If it's version-gated or outside the diff, it's environmental/pre-existing noise —
record it as "unrelated CI noise (not touched)" in the PR body, don't block the merge.

## Decision summary

| Symptom | Verdict | Action |
|---|---|---|
| All checks red, "account locked/billing" annotation | CI blocked at account level | Merge if mergeable + no required checks; comment why |
| Failure in file NOT in branch diff | Pre-existing | Out of scope; note in PR |
| Failure only on local Node16/Py3.9 but diff is fine | Env version mismatch | Use newer local toolchain to verify; note in PR |
| Failure in file IN diff, real error trace | Code broken | Fix before merge |
