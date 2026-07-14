# ADR-0035: Bounded resource homeostasis controller contract

- Status: accepted
- Date: 2026-07-13
- Related: issue #179

## Context

Issue #179 needs a narrow, deterministic contract for resource homeostasis
inside the agent tree without wiring schedulers, providers, or runtime repair
loops. The missing piece was not execution plumbing; it was a reusable policy
layer that can answer, from typed observations alone:

- when resources are under pressure,
- when quality has degraded enough to require corrective action,
- when safety or missing telemetry should force fail-safe behavior, and
- what receipt-safe evidence can be emitted without leaking secrets.

The scope for this slice is intentionally bounded to pure evaluation plus
fixtures and tests. Production polling, background loops, live provider repair,
and runtime/MCP transport integration remain out of scope.

## Decision

`agent/resource_homeostasis.py` defines the contract as a stdlib-only,
deterministic evaluator.

- `ResourceObservation`, `QualityObservation`, and `SafetyObservation` are the
  typed inputs.
- `HysteresisThreshold` provides stable enter/exit behavior so the controller
  does not flap on small metric oscillations.
- `HomeostasisPolicy` declares thresholds, required safety checks, deterministic
  corrective actions, and a bounded total action-cost budget.
- `ResourceHomeostasisController.evaluate()` computes one of three modes:
  `nominal`, `degraded`, or `fail_safe`.
- `ActionCostReceipt` records whether each corrective action was applied or
  skipped because of the current budget bound.
- `redact_evidence()` strips secret-like fields from evidence before decisions
  are serialized or logged.

Fail-safe degradation is explicit. Missing required observations and unsafe
safety checks are treated as contract violations and force `fail_safe` with
mandatory autonomy-pausing actions instead of optimistic continuation.

## Consequences

- Resource control becomes deterministic and testable without live telemetry
  loops.
- Hysteresis prevents repeated enter/exit thrash around the threshold edges.
- Action-cost receipts bound the controller's own remediation plan and make
  skipped work auditable.
- Evidence can be attached to ledgers or future telemetry surfaces without
  leaking secrets.
- The contract is ready for later scheduler/runtime integration without
  deciding that integration here.

## Alternatives considered

- Wire the controller directly into schedulers now: rejected because issue #179
  explicitly forbids production scheduling/runtime integration in this slice.
- Treat missing observations as neutral: rejected because silent optimism hides
  blind spots and defeats fail-safe behavior.
- Use non-deterministic scoring or weighted heuristics: rejected because
  bounded, auditable corrective actions need reproducible decisions.
