# ADR-0009: Bounded restart recovery for ambiguous effects

Status: accepted as a bounded proof slice for issue #183

## Decision

`agent.restart_recovery.EffectJournal` is a small, versioned JSONL model for
the interval in which an actuator may have committed an idempotency-sensitive
effect but the process lost its response. It is aligned with the existing
`TaskEnvelope` and `agent.telemetry.receipts.Receipt` contracts:

- `task_id`, `correlation_id`, and `envelope_hash` bind an effect observation to
  the resumed task envelope;
- `receipt_sha` points at the existing content-addressed receipt, without
  changing the receipt schema;
- each line is fsynced before the observation is considered durable;
- exact duplicate lines are idempotent, and a committed observation cannot be
  superseded by a stale downgrade.

## Recovery matrix

| Durable observation | Restart decision | May execute effect? |
| --- | --- | --- |
| `committed` + receipt | `skip_committed` | No |
| `not_committed` | `retry` under the same idempotency key | Yes |
| `unknown` with reason | `reconcile_unknown` | No |
| `pending` or no record | `reconcile_unknown` | No |

The important safety rule is that absence of a response is not evidence of
`not_committed`. Unknown remains visible and must be reconciled by a verifier
or an operator before the effect is attempted again.

## Scope and limitations

The focused tests prove journal reconstruction in a new Python object,
committed no-retry, not-committed retry eligibility, explicit unknown, receipt
and envelope hash carriage, duplicate append idempotency, and committed-state
monotonicity.

This does **not** claim a full reboot E2E. It does not yet prove process or
machine reboot, goal/anchor reconstruction, projection hash equivalence,
notification deduplication, handoff recovery, cross-machine behavior,
external-effect verification, compensation, or duplicate-effect-rate and
recovery-time metrics. Wiring this model into every actuator and the runtime
kernel is a separate integration step.
