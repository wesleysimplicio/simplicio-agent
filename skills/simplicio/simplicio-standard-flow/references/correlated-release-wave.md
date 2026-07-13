# Correlated release wave

Use this reference when several Simplicio repositories form a dependency chain, especially mapper → dev-cli → loop.

## Canonical sequence

1. Re-query issue and PR state for all repositories.
2. Finish and merge mapper implementation.
3. Publish the mapper release and verify its tag/release URL.
4. Update the dependent dev-cli floor to the published mapper version. Regenerate generated dependency docs, update version fixtures/changelog, validate, open and merge the dev-cli release PR, then publish the dev-cli release.
5. Update the dependent loop floor to the published dev-cli version. Synchronize all package/plugin metadata, validate, open and merge the loop release PR, then publish the loop release.
6. Run final broad validation only when the wave's testing policy permits it.
7. Re-query GitHub. Only close issues when the user explicitly authorizes it; after closing, verify `open issues = 0` and `open PRs = 0`.

## Evidence contract

Record separately:

- `MERGED|` — PR state is `MERGED`, with merge commit and base branch.
- `RELEASED|` — release/tag URL exists and targets the expected base branch.
- `MEASURED|` — focused or broad tests actually ran and returned the stated result.
- `UNVERIFIED|` — hosted checks, full suite, package publication, or end-to-end behavior were not proven.
- `CLOSED|` — issue state is `CLOSED`, with `closedAt` and URL.

Never collapse these into one claim such as “everything is complete.”

## Safe merge/close procedure

- Use normal merge only; never use `--admin` to bypass required checks.
- If checks fail because the provider is unavailable or billing-locked, preserve the exact blocker and separate it from local focused evidence.
- Do not close issues merely because a similarly titled PR exists. Confirm the PR is merged into the intended base and that the release dependency chain is complete.
- A merged PR can still leave the issue open by policy; close-gate is a separate, explicit operation.

## Common failure mode

A parallel drain may produce many valid PRs before the upstream release exists. That is acceptable as preparation, but downstream merges/releases must wait for the dependency predecessor. Conversely, if a worker reports “implemented” but the live branch has no commit/PR, inspect the worktree and re-dispatch repair instead of trusting the report.
