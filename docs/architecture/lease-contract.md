# Issue claim lease contract

This document defines the bounded agent-side claim boundary for Issue Factory
orchestration. The durable record is `simplicio.lease/v1`; the GitHub lifecycle
caller remains responsible for choosing the repository and issue number.

## Lease record

Each issue has at most one row in the SQLite store, keyed by `issue`. The row
contains `lease_id`, `holder`, `acquired_at`, `ttl_s`, `heartbeat_at`, a
monotonically increasing `fencing_token`, `status`, an optional
`takeover_reason`, and an optional GitHub `comment_id`.

`acquire` runs under SQLite `BEGIN IMMEDIATE`. An existing lease is active when
`now <= heartbeat_at + ttl_s`; an active row is returned unchanged and no
comment mutation occurs. Only an expired row can be taken over, and takeover
increments `fencing_token` so stale workers cannot safely perform later
mutations. `renew` and `release` require the exact holder, lease id, and fence
token; repeated release by that same fenced lease is an idempotent no-op, while
an older fence is rejected even if the newer lease has already been released.
Renewal timestamps are monotonic: a renewal at the current heartbeat is a
no-op, and a clock regression is rejected. Timestamps are normalized to finite
numbers before persistence so the rendered receipt is stable before and after
a store reload.

## GitHub comment policy

Claim comments carry the marker `<!-- simplicio-claim -->`. The first successful
acquire upserts one marker comment. Renewals, takeover, and release pass the
persisted `comment_id` to the sink and edit that comment. A sink failure is
returned as `comment_error`; it never falls back to creating a second comment.
An idempotent acquire retries synchronization only when the durable lease has
no `comment_id`, covering a committed lease whose first comment request failed.
The `GhIssueCommentSink` discovers an existing marker before its first create,
which also makes recovery after a process crash safe against duplicate spam.

Comment receipts use sorted, compact JSON with normalized timestamps. The
marker and receipt body therefore remain deterministic for a given lease while
heartbeat, takeover, and release transitions still produce edits rather than
new comments.

The implementation is intentionally a narrow boundary: it does not claim the
full six-worker #315 replay, live GitHub sandbox execution, status telemetry,
benchmark budget, or issue closure. Those remain `UNVERIFIED|` until the
runtime-side integration and independent live gates exist.
