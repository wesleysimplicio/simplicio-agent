# GitHub PR follow-up review under constrained auth

Use this when a PR already has reviewer feedback and the goal is to inspect comments, adjust the branch, validate locally, and post a precise follow-up.

## Durable lessons

1. **Prefer REST over GraphQL for PR feedback when token scopes are narrow**
   - If `gh pr view --comments` or similar GraphQL-backed commands fail with scope errors like `read:org`, switch to REST endpoints immediately.
   - Reliable reads:
     - `gh api repos/<owner>/<repo>/pulls/<pr>/reviews`
     - `gh api repos/<owner>/<repo>/issues/<pr>/comments`
   - This avoids blocking on org-scope gaps while still retrieving the actionable review text.

2. **Review the diff for unrelated changes before replying**
   - Run a file-level diff (`gh pr diff <pr> --name-only`) to detect extra files that do not belong to the PR thesis.
   - If review feedback says a file is unrelated, split or remove it before responding.

3. **Validate on the branch with the right extras enabled**
   - For Hermes Agent, local verification often needs `uv run --extra ...` rather than bare `pytest`.
   - Common pattern:
     - ACP work: `uv run --extra dev --extra acp pytest ...`
     - Slack work: `uv run --extra dev --extra slack pytest ...`
   - A bare interpreter/test invocation can fail at collection and is not evidence against the fix itself.

4. **Post PR replies from a file, not an inline shell string**
   - If the comment contains backticks, code spans, `:free`/`:beta`, or other shell-sensitive text, write the body to a temp markdown file and use:
     - `gh pr comment <pr> -F /abs/path/comment.md`
   - This avoids shell interpolation and accidental command substitution.

## Recommended sequence

1. Read reviews/comments via `gh api` REST endpoints.
2. Confirm whether the review identifies a real regression, missing test, or unrelated hunk.
3. Inspect changed files to verify scope.
4. Amend branch.
5. Re-run targeted local validation with the needed `uv` extras.
6. Push branch.
7. Post a concise follow-up comment with exactly what changed and the measured validation command/result.

## Response shape for the PR comment

- What was changed
- Why that addresses the reviewer concern
- Exact validation command(s)
- Measured result (`81 passed`, `455 passed`, etc.)

Keep the comment factual and compact; no speculative claims about CI until remote checks actually finish.
