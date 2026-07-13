# Readiness Gap Audit

Use this read-only audit when the user asks whether Simplicio is updated, ready, or what remains before a wave/final delivery.

## Command matrix

```bash
# Runtime health
simplicio --version
simplicio doctor --json
simplicio runtime map --repo <repo> --for-llm markdown
simplicio memory "readiness gaps <repo>"

# Installed contract versions
simplicio-mapper --version --json
simplicio-py --version --json
simplicio-loop --version

# Repository/PR state
for repo in <repos>; do
  git -C "$repo" fetch origin --prune
  git -C "$repo" status --short --branch
  git -C "$repo" log -1 --oneline
  gh pr list -R <owner>/<repo> --state open --limit 100 --json number,state,title,headRefOid
  gh issue list -R <owner>/<repo> --state open --limit 500 --json number
 done

# CI diagnosis
 gh run view <run-id> -R <owner>/<repo>
 gh run view <run-id> -R <owner>/<repo> --json jobs
 gh run view <run-id> -R <owner>/<repo> --log-failed

# Capacity
 df -h <volume>
 du -sh <repo>/target <repo>/.venv <repo>/node_modules ~/.simplicio/cache 2>/dev/null
```

## Interpretation rules

- A runtime `warning` is not equivalent to unavailable runtime. Separate reachable execution from missing model/adapter/evidence readiness.
- A direct adapter version is stronger evidence than a doctor's `unknown`; classify the latter as a detection/compatibility gap.
- A PR with `mergeable` and no checks is not verified. A merged PR with no checks still needs local/final smoke evidence before closing the issue.
- If a run's jobs have zero steps/logs, read the human-readable annotations. Billing/account lock or runner provisioning messages are infrastructure blockers, not evidence that the code failed.
- Do not call CI red when the runner never started; report `CI unavailable — infrastructure` and retain `UNVERIFIED|` for behavior.
- Sum issue counts with a real command. Merged PRs do not imply issue closure when PR bodies say `Closes nothing.`.
- Treat `target/`, caches, build outputs, and disposable environments as reclaim candidates, but preserve `.simplicio` evidence, worktrees, and source state until audited.
- Never delete during the inventory. Produce a ranked remediation list first.

## Human report shape

1. **Blockers:** external/infrastructure/resource conditions.
2. **Unverified behavior:** PRs/issues lacking executable evidence.
3. **Parity gaps:** installed package versus runtime detection/source versions.
4. **Backlog:** per-repository open counts and total.
5. **Capacity:** measured free disk and reclaim candidates.
6. **Next order:** unblock infrastructure → reclaim safe artifacts → run focused/final tests → review/merge → live issue close-gate.

Always use `MEASURED|` for command-backed facts and `UNVERIFIED|` where execution was intentionally deferred.