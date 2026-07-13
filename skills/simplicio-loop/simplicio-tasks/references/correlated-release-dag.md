# Correlated release DAG

Use this recipe when several repositories consume one another and their releases must land in order.

## Discovery

1. Query live default branches, package versions, tags/releases, open issues, and all PR states.
2. Deduplicate by issue, branch, PR, merge commit, and release tag.
3. Treat “merged PR” and “closed issue” as separate facts. A merged implementation may still require a release, and an issue may remain open until a close-gate.
4. Identify the first upstream artifact that downstream code must consume.

## Ordering contract

```text
upstream implementation
  → upstream release PR
  → upstream merge/tag/package publication
  → live tag/package verification
  → downstream dependency update
  → downstream release
  → next consumer update
  → final cross-repo tests
  → live issue re-query and close-gates
```

Preparation can be parallel, but merges and release publication are serialized at dependency boundaries. Never pin a downstream project to a version that is only present on a branch or local checkout.

## Release gate

For each package:

- synchronize every version source (`pyproject.toml`, `package.json`, lockfile, module constant, generated metadata);
- update changelog/release notes without copying malformed escaped newlines;
- run the repository’s version-sync/static checks;
- commit only explicit release files;
- push a release branch and open a PR;
- wait for required checks or record the concrete infrastructure blocker;
- merge normally, create/push the tag or GitHub release, and query the live tag/package registry;
- only after the live artifact is verified, update the next consumer.

A GitHub Actions billing/account lock is a release blocker, not a code failure and not permission to use an admin merge. Keep the release PR open and mark publication `UNVERIFIED|` until the gate is available.

## Final gate

After the last consumer release:

- run the deferred cross-repository tests and real smoke paths;
- review the final diffs adversarially;
- re-query each issue and PR live;
- close an issue only after merged PR + in-turn evidence + live state confirms closure;
- open a new aggregate release only if the user’s explicit zero-open-issues condition is met.

## Merge pressure and red-check handling

If the user explicitly requests merges while hosted checks are red or unavailable, use only the repository's normal merge path and record the exact live state. Never use `--admin`, bypass branch protection, or relabel failed checks as green. The resulting release must remain `UNVERIFIED|` until local/final tests and real package/tag verification run. This is an exceptional user-directed merge decision, not the default release gate.

## Release worktree targeting

Create the release branch from the fetched remote default (`origin/main` or `origin/master`) before editing. Verify `git rev-parse HEAD` against the remote base and pass the release worktree explicitly to `simplicio edit --plan --repo`; editing the canonical checkout can silently place release metadata on a stale local branch. If metadata was edited on the wrong checkout, stash only the explicit release files, reset the checkout to the remote base, create the release branch, and reapply the stash; verify the final diff and branch before commit.

## Common pitfalls

- Starting all downstream agents as if release dependencies did not exist.
- Releasing from a stale local branch instead of `origin/main`.
- Assuming a release tag predates or includes a later merged PR.
- Treating CI with zero steps/logs as a code-test failure; inspect annotations for infrastructure causes.
- Closing issues because a PR merged while its release or acceptance smoke remains unverified.
- Creating duplicate PRs for already merged branches.
