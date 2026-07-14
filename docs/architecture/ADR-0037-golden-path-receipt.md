# ADR-0037: Bounded request-to-delivery receipt

*Status: Accepted — 2026-07-14*

## Context

Issue #211 already has a fixture-driven golden-path harness in
`agent/golden_path.py`. Its per-operation transport receipts prove the run,
but consumers still need one small artifact that connects the request,
independent final-state requery, evidence references, and accepted delivery.

The fixture run is not a clean-machine or production E2E test. A receipt that
does not say so invites an over-broad completion claim.

## Decision

`tools/golden_path.py` builds and verifies a canonical
`simplicio-agent/issue-211-golden-path-receipt/v1` receipt from a completed
golden-path result. It records only deterministic proof-bearing fields:

* request identity and write-set;
* closed lifecycle plus evidence references;
* passing independent final-state requery;
* normalized transport operation outcomes; and
* accepted delivery target.

The proof scope is always `fixture_only`, with
`clean_machine_e2e: not_claimed` and `external_services: false`. Runtime
request ids, timings, and other transport noise are intentionally omitted.
The receipt includes a SHA-256 over its canonical JSON payload; verification
rejects tampering, missing evidence, failed requery, unaccepted delivery, and
any clean-machine claim.

## Consequences

The existing harness remains the execution proof, while this focused layer is
portable and independently auditable. The artifact can support a bounded
request-to-delivery claim without implying clean-machine E2E coverage; a
future clean-machine run must publish a separately scoped receipt.
