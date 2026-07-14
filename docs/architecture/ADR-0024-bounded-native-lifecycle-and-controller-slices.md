# ADR-0024: Bounded native lifecycle and adaptive-controller slices

- Status: bounded contract
- Date: 2026-07-14
- Related: issues #319 and #320, ADR-0023

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
  queue pressure, working-set entropy, and marginal gain.

Both contracts are pure and have no daemon, scheduler, provider, or gateway
integration. They are suitable for a later Rust implementation to consume as
golden behavior fixtures.

## Evidence boundary

Focused tests cover startup/readiness, protocol incompatibility, reconnect
boundedness and delay selection, generation changes, stop transitions,
pressure/throttle behavior, hysteresis, bounded scale-up, decay, and JSON
stability. This slice makes no production p50/p95, benchmark-gain, or live
crash-isolation claim; those require the compiled runtime and an evidence-
producing benchmark/live-process gate.
