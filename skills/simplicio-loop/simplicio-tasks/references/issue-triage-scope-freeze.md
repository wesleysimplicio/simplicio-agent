# Issue triage under scope freeze

## When to use
Use this pattern when the user asks to clear a queue of GitHub issues / tickets in a repo that has a standing scope freeze (for example, a kernel-only freeze or an agent-parity freeze).

## Core procedure
1. **Group issues before action**
   - Cluster by theme: runtime gaps, performance, tech debt, product/UX, duplicates, and stale/no-op.
   - Parallelize discovery: `gh issue view` + targeted repo scans per cluster.

2. **Classify each issue into one of four buckets**
   - `in-scope actionable` → keep open; identify smallest verifiable next step.
   - `out-of-scope / frozen` → close with `--reason "not planned"` and optionally retarget in the comment.
   - `duplicate` → close with `--reason duplicate --duplicate-of <number>`.
   - `already satisfied by code` → close with `--reason completed` only when the repo evidence is current and direct.

3. **Act only on evidence**
   - Prefer `gh issue view --json ...` for the issue body/state/labels.
   - Confirm code reality with repo inspection or grep/search before closing as completed or duplicate.
   - If the queue item is stale/no-op in the checkout, close it rather than inventing a fix.

4. **Verify after the batch**
   - Re-query open issues with `gh issue list --state open` (or equivalent API/listing command).
   - Confirm the target issue numbers are no longer open.
   - Keep a short evidence trail: close commands + verification listing.

## Pitfalls
- Don’t spend time on a full implementation for issues that are clearly frozen by repo policy.
- Don’t assume `gh issue close` defaults; pass the reason explicitly.
- Don’t mix “duplicate” and “not planned” reasoning; choose the best fit from evidence.
- Don’t close as `completed` unless the code path really exists now, not just in an old summary.

## Useful commands
- `gh issue view <num> --json number,title,state,body,labels,comments`
- `gh issue close <num> --reason "not planned"`
- `gh issue close <num> --reason duplicate --duplicate-of <other>`
- `gh issue close <num> --reason completed`
- `gh issue list --state open --limit 100 --json number,title`
