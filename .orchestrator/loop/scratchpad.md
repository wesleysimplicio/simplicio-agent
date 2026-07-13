---
iteration: 1
max_iterations: 3
completion_promise: "ISSUE-183 RESTART RECOVERY SLICE DONE"
evidence_required: true
mode: converge
started_at: "2026-07-13T19:52:00Z"
---

Implement issue #183 as a bounded restart/idempotency recovery slice: add a
versioned durable effect-state model aligned with TaskEnvelope and existing
content-addressed Receipt records. A fresh journal instance must recover
committed as SKIP_COMMITTED (never retry), not_committed as RETRY, and unknown
as RECONCILE_UNKNOWN with an explicit reason. Add focused tests and docs.

This is a bounded model/harness, not a full process or reboot E2E. Do not claim
that goal/anchor reconstruction, projection equivalence, notification or
handoff recovery, cross-machine behavior, or duplicate-effect rates are proven.
Run the Simplicio Runtime CLI if available, plus focused tests and Ruff, then
commit this branch and record measured results.

The loop helper scripts referenced by the skill are absent in this checkout;
the durable scratchpad and real command receipts are the available evidence.
