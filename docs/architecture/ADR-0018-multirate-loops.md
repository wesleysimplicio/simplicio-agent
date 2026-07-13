# ADR-0018: bounded deterministic multi-rate scheduler contract

- Status: accepted
- Date: 2026-07-13
- Related: issue #180, `agent/multirate_scheduler.py`, `tests/agent/test_multirate_scheduler.py`

## Context

Issue #180 needs a bounded scheduler contract for future multi-rate agent
loops, but this slice is explicitly not allowed to wire production
conversation loops, providers, or goal policy. The gap was in the control
plane itself: there was no typed ownership model for event/reflex/attention/
deliberation/consolidation lanes, no deterministic backpressure story, and no
contract for what happens when a slow lane misses its budget or fails.

The requirement is therefore narrower than "make the loop multi-rate". It is
"define the scheduler semantics in isolation so later production wiring has an
auditable contract to adopt".

## Decision

`agent/multirate_scheduler.py` now defines the bounded contract layer:

- `LaneName` fixes the five owned lanes in order:
  `event -> reflex -> attention -> deliberation -> consolidation`.
- `LaneConfig` and `MultiRateSchedulerConfig` version cadence, queue caps,
  latency budgets, token budgets, priorities, starvation windows, and
  escalation targets.
- `WorkItem` gives every unit of work an explicit `owner`, which means each
  lane has a single owner slot. Re-enqueueing the same owner replaces stale
  queued work rather than duplicating it.
- `MultiRateScheduler` owns bounded queues, deterministic selection, per-tick
  token resets, escalation, and failure quarantine.
- Priority is age-aware: base lane priority is combined with an aging bonus so
  slower lanes eventually outrank a continuous stream of fresher fast-lane
  work.
- Budget misses are explicit. When a lane cannot satisfy latency or token
  budget, work is escalated to the configured slower lane; if no target exists
  or the target is also saturated, the item is dropped with a recorded reason.
- Slow-lane failures are quarantined. A failure in `deliberation` or
  `consolidation` records a failure event and may requeue the item to the
  configured slower lane, but it never blocks event/reflex dispatch.

The scheduler is deterministic by construction: no wall clock, no threads, no
I/O, and no hidden randomness. Time is represented as explicit ticks so
contract tests can reason about latency budgets without production timers.

## Consequences

- Production wiring can adopt a tested scheduler contract later instead of
  inventing semantics inside the conversation loop.
- Backpressure, escalation, and slow-lane failure are now observable as typed
  events rather than implicit side effects.
- Event ownership is explicit, preventing stale duplicated work for the same
  owner in the same lane.
- The no-starvation rule is testable with deterministic fixtures.
- This ADR does not claim any throughput or latency benchmark evidence. It only
  defines and tests the control-plane contract.

## Alternatives considered

- Wiring the scheduler directly into conversation loops in this issue:
  rejected because the issue bounds forbid production integration.
- Unbounded per-lane queues with caller-managed dropping: rejected because it
  hides backpressure and makes overload behavior non-deterministic.
- Pure fixed-priority dispatch with no aging: rejected because it starves slow
  lanes under sustained reflex/event pressure.
- Treating slow-lane failures as global scheduler failure: rejected because the
  contract needs safe degradation, not system-wide deadlock.
