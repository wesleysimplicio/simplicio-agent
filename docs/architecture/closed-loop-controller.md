# Closed-loop controller contract

`agent.closed_loop_controller` is the bounded deterministic policy slice for
issue #161. It accepts a goal string, an explicit `StateEstimate`, candidate
actions, anti-oscillation state, and a versioned `ControllerPolicy`. It
returns exactly one typed next-step decision:

- `ActionDecision`
- `ObserveDecision`
- `WaitDecision`
- `ClarifyDecision`
- `BlockDecision`

The controller is pure. It does not execute tools, mutate authority, persist
state, or bypass the Runtime gate. It evaluates only the next observation
boundary, so callers must re-enter the controller after each observed effect.

## Fail-closed state handling

- `missing_inputs` never degrade to defaults; they force `ObserveDecision` with
  `reason_code=missing_observations`.
- `conflicts` remain explicit and force `ObserveDecision` with
  `reason_code=conflicting_observations`.
- stale/unknown freshness forces `ObserveDecision`.
- low precondition confidence forces `ObserveDecision`.
- committed-but-unverified effects force observation and reconciliation before
  any retry.
- unavailable capability returns `WaitDecision`, not a silent fallback.

## Policy and budget constraints

Every decision includes:

- `active_constraints`: the versioned policy thresholds and active budgets;
- `constraint_receipts`: explicit pass/block/clarify/wait/suppress receipts for
  candidate eligibility, human gates, mutation policy, budget ceilings, and
  anti-oscillation suppression.

This keeps goal/policy/budget constraints visible without creating another
governor or state store.

## Anti-oscillation receipts

The caller supplies `AntiOscillationState` with a failure fingerprint,
repeated-failure count, cooldown remaining, and suppressed digests. The
controller emits an `AntiOscillationReceipt` on the resulting decision:

- repeated failures suppress the last oscillating action digest;
- active cooldown yields `WaitDecision`;
- a repeated fingerprint with no safe alternative yields `BlockDecision` with
  `reason_code=strategy_switch_required`;
- if a different safe candidate exists, the controller can still return
  `ActionDecision`, but the suppression receipt remains attached.

The contract deliberately does not own planning, state persistence,
reconciliation storage, resource governance, or execution. Those remain with
the existing goal contract, awareness work, resource governor, and Runtime
action gate.
