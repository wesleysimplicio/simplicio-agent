# Runtime evolution token-savings notes

Session finding: the repo map can be too broad when generated trees are included.

## Token-saving opportunities to preserve

1. **Compact maps**
   - Prefer source-only maps by default.
   - Exclude generated trees unless explicitly requested: `node_modules/`, `.venv/`, `venv/`, `.git/`, build output, archives, screenshots, and similar bulk artifacts.
   - Add a delta map for repeat turns: summarize only changed files + direct dependents.
   - Cache maps by repo hash + changed-surface fingerprint; invalidate only on real surface changes.

2. **Evidence refs**
   - Emit stable receipt IDs for validation, smoke tests, and PR evidence.
   - Prefer artifact handles and file:line receipts over rereading raw logs.
   - Keep a deterministic chain: task anchor → test output → PR body → closeout comment.

3. **Deterministic edits**
   - If the change is already decided, route it through zero-token mechanical edit/apply paths.
   - Reserve freeform generation for ambiguity, planning, or failure recovery.

4. **Parallel fan-out**
   - Split work into independent lanes: map/digest, evidence, edit plan, validation, review.
   - Fan out only when lanes do not depend on one another.
   - Serialize same-file or same-contract changes; parallelize everything else.

## Session-specific signal

A repo scan in this session showed the bulk of file count coming from generated trees, which makes broad maps expensive and noisy. That is a strong reason to default to source-only orientation and changed-surface deltas in future runtime-evolution work.
