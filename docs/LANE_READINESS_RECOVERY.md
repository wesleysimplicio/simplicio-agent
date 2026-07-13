# Lane readiness recovery (issue #142)

`agent.telemetry.lane_readiness` is the canonical, machine-readable readiness
contract for governed agent lanes. It replaces silent non-progress ("the loop
just isn't moving") with an explicit `LaneReadinessReceipt` carrying one of
three states and, when blocked, one or more precise `reasons`:

| State | Meaning |
|---|---|
| `blocked` | At least one hard condition is unmet — see the reason table below. |
| `artifacts_ready` | Artifacts are present, fresh, any held lock is legitimate, and required context is available — but no handoff target exists yet (`no_handoff_targets`). |
| `handoff_ready` | Everything above, plus at least one handoff target. Safe to hand off. |

A single lane can be evaluated repeatedly as its state changes; the intended
path is `blocked -> artifacts_ready -> handoff_ready` (see
`tests/agent/telemetry/test_lane_readiness.py::test_lane_transitions_blocked_to_artifacts_ready_to_handoff_ready`
for a runnable reference of that exact transition, including the
append-only receipts each step produces via
`agent.telemetry.receipts.record_receipt`).

## Recovering from each `blocked` reason

**Never remove a lock to "unblock" a run.** A lock that is still legitimate
(see below) means another worker is actively using the artifact; removing it
corrupts that worker's state. Every recovery path here fixes the underlying
condition instead of clearing the guard that reports it.

### `artifacts_missing`

One or more required artifacts (e.g. a mapper project-map, symbol-index, or
call-graph) do not exist yet.

1. Confirm the survey operator actually ran for this lane:
   `simplicio-mapper status <repo> --json`.
2. If it never ran, run it: `simplicio-mapper index <repo> --json` (or the
   two-tier `scan` + `status --await` flow — see
   `skills/simplicio-loop/simplicio-loop/references/mapper-freshness-and-task-contract.md`).
3. Re-evaluate the lane. Do **not** synthesize a fake `ArtifactStatus(present=True)`
   to skip the check — that produces a false `handoff_ready` receipt, which is
   exactly the "silent non-progress" this contract exists to prevent.

### `artifacts_not_fresh`

The artifact exists but is considered stale relative to the current source
tree (typically because generated run/loop state was written where the
mapper treats it as source churn).

1. Make sure loop/run state is written under a path the survey operator
   ignores (e.g. `.simplicio/loop-runs/`), not `.orchestrator/runs/` or
   another path the mapper fingerprints as source.
2. Re-index: `simplicio-mapper index <repo> --json`, then confirm freshness
   with `simplicio-mapper inspect <repo> --json --await` (`status.fresh` must
   be `true` — the field lives under `status`, not the top level).
3. If the mapper goes stale again immediately after a clean re-index, that is
   a freshness-boundary bug, not a retry-until-it-passes situation — stop and
   record the repeating fingerprint (see the mapper-freshness reference doc)
   instead of looping on the same fix.

### `no_handoff_targets`

Artifacts, lock, and context are all fine, but there is nothing to hand off
to yet (no branch, PR, or downstream lane declared). This is the
`artifacts_ready` state, not `blocked` — it is expected, transient progress,
not a failure.

1. Produce the actual handoff target for the lane (open the branch/PR, or
   register the downstream lane) as normal delivery work.
2. Re-evaluate; once at least one target exists the receipt becomes
   `handoff_ready`.

### `needs_broader_context`

The lane declared a context surface it requires (e.g. `call-graph`,
`precedent-index`) that is not in the set of surfaces currently available.
`LaneReadinessReceipt.missing_context` names exactly which surface(s) are
missing — never guess from the state name alone.

1. Load or generate the named surface(s) (e.g. run the mapper's call-graph
   pass, or fetch the precedent index) before retrying.
2. If a surface can never be produced for this lane (no data source exists),
   remove it from `required_context` deliberately and record why — do not
   leave it silently unsatisfiable.

### `lock_stale`

A mapper/index lock is held, but its last heartbeat (or acquisition time, if
no heartbeat was recorded) is older than the lock's TTL
(`LockInfo.stale_after_seconds`, default 15 minutes), or the lock has no
timestamp at all to prove liveness.

1. Confirm the presumed holder process is actually gone (check the PID/job
   the lock names, if it records one) before touching the lock file.
2. If the holder is confirmed dead, repair the lock through the owning
   operator's own release path (e.g. `simplicio-mapper` lock-repair /
   `--force-release` command if one exists for your installed version) —
   never `rm` the lock file directly, and never treat a stale classification
   alone as authorization to remove it without confirming the holder is dead.
3. If the holder is still alive (a heartbeat simply hasn't been written
   recently, e.g. a very long single mutation), do not repair anything —
   raise the lane's `stale_after_seconds` TTL for that class of long-running
   holder instead of forcing the lock into a legitimate state it must earn.

## Distinguishing legitimate vs. stale locks

`LockInfo.status()` is the single source of truth: a lock with a holder and a
heartbeat (or acquisition timestamp) within `stale_after_seconds` is
`legitimate` and is never a block condition. A lock with no timestamp, an
unparseable timestamp, or a heartbeat older than the TTL is `stale` and
surfaces as the `lock_stale` reason. This mirrors the real incident this
issue documents: the mapper lock during the six-lane run *was* legitimate and
was correctly left alone — the missing piece was making that judgment
explicit and machine-readable instead of an implicit assumption.
