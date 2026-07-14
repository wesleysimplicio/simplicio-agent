# ADR-0038: Bounded native lifecycle and adaptive-controller slices

- Status: bounded contract
- Date: 2026-07-14
- Related: issues #319 and #320, ADR-0037

## Decision

This migration slice adds two pure, deterministic boundaries that a future
compiled daemon can shadow-run without owning processes or schedulers:

- `tools/runtime_lifecycle.py` composes the runtime version handshake with
  explicit startup/health probes and a versioned lifecycle reducer. It fails
  closed on incompatible protocol, bounds reconnect attempts, and emits
  JSON-safe state and decision receipts.
- `agent/adaptive_controller.py` evaluates one resource/queue observation at a
  time. Resource pressure throttles by one step, hysteresis prevents premature
  recovery, low marginal gain decays concurrency, and scale-up is gated by
  queue pressure, working-set entropy, and marginal gain. Every scale-up is a
  one-worker minimal action; the PID output is bounded and emitted as policy
  evidence rather than being allowed to create an unbounded burst.
- `AdaptiveController.bound_fan_out()` adapts the resulting target to an
  existing batch-dispatch interface by selecting at most the policy and
  decision limits in input order. It returns a `FanOutPlan` with a
  JSON-safe receipt (`requested`, `allowed`, `selected`, and `truncated`) and
  does not create workers or perform dispatch itself.

Both contracts are pure and have no daemon, scheduler, provider, or gateway
integration. They are suitable for a later Rust implementation to consume as
golden behavior fixtures.

## Evidence boundary

Focused tests cover startup/readiness, protocol incompatibility, reconnect
boundedness and delay selection, generation changes, stop transitions,
pressure/throttle behavior, hysteresis, bounded minimal scale-up, decay,
entropy gating, PID integral clamping, bounded fan-out, fixture equivalence,
and JSON stability. This slice makes no production CPU, memory, p50/p95,
benchmark-gain, or live crash-isolation claim: those remain `UNVERIFIED` until
an evidence-producing benchmark/live-process gate runs against the compiled
runtime and representative workloads.
