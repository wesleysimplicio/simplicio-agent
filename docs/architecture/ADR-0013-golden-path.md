# ADR-0013: Deterministic golden-path harness

*Status: Accepted — 2026-07-13*

## Context

Issue #211 needs one bounded slice that proves the current `TaskEnvelope`
lifecycle and the CLI-first Simplicio transport can drive the same
deterministic task without widening either contract. The missing piece was a
small vertical harness that:

* uses the real `TaskEnvelope` state machine from `agent/task_envelope.py`,
* uses the real CLI-first transport from `tools/simplicio_transport.py`,
* emits durable receipts for lease, mutation, validation, evidence, and
  delivery,
* re-reads workspace state independently before the envelope is allowed to
  close, and
* exercises both the healthy CLI path and the explicit `cli_unavailable`
  fallback path.

## Decision

`agent/golden_path.py` owns a fixture-driven harness for this bounded slice.
It loads one deterministic scenario from `fixtures/golden-path/`, creates a
real `TaskEnvelope`, and walks it through:

`received -> oriented -> planned -> claimed -> executing -> validating -> evidence_ready -> delivered -> closed`

The harness uses `SimplicioTransport` for the operational steps:

* `orient` to establish the write-set context,
* `checkpoint` for the lease receipt,
* `mechanical_edit` for the write-set mutation,
* `gate` for validation,
* `ledger` for delivery.

Every step records a content-addressed receipt under the fixture workspace
`.receipts/` directory. The close gate does not trust transport output alone:
after validation, the harness performs an independent final-state requery from
disk and only transitions to `evidence_ready`/`closed` if the observed
workspace exactly matches the expected final state.

## Consequences

* The bounded slice proves the transport and envelope contracts compose on a
  real path without editing either subsystem.
* The happy path is deterministic because the workspace, mutation, and
  validation inputs are fixture-backed.
* The fallback path remains explicit: only CLI unavailability uses MCP, and
  the resulting receipts preserve `fallback_reason: "cli_unavailable"`.
* Future surfaces can reuse this harness shape when they need a small
  end-to-end proof before broader integration.
