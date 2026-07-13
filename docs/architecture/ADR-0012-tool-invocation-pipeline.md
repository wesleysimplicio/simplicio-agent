# ADR-0012: typed tool invocation pipeline for bounded worker execution

- Status: accepted
- Date: 2026-07-13
- Related: issue #228, `agent/tool_invocation_pipeline.py`, `tests/agent/test_tool_invocation_pipeline.py`

## Context

Issue #228 asks for a bounded slice that makes tool invocation lifecycle
ordering explicit without rewriting existing executors. The old module was a
small hook runner with partial stage coverage and weak metadata defaults:

- stage naming mixed required pipeline stages with legacy-only steps
- evidence was not typed and did not consistently carry attempt metadata
- blocked/error paths could miss receipt-level deduplication
- there was no first-class serial executor adapter for callers that already
  run tools synchronously
- external results could be copied verbatim into evidence payloads

The user also constrained the change surface to this module, its focused test
file, this ADR, and local fixtures. Existing worker files and executors had to
remain untouched.

## Decision

`agent/tool_invocation_pipeline.py` now defines a typed
`ToolInvocationPipeline` with the required stages only:

1. `resolve`
2. `normalize`
3. `authorize`
4. `classify`
5. `guardrail`
6. `action-gate`
7. `checkpoint`
8. `execute`
9. `persist`
10. `evidence`

The module also owns:

- a typed `ToolInvocationMetadata` contract with fail-safe defaults
- `ToolDecision` for guardrail/action-gate results
- `ToolInvocationReceipt` and once-per-attempt receipt writing
- `ToolInvocationAttempt` as the immutable per-stage state carrier
- `SerialToolExecutorAdapter` so synchronous executors can participate without
  modification
- split-completion trace canonicalization so replayed traces remain bounded to
  known stages, in canonical order, with duplicate/unknown entries ignored
- external-result redaction inside evidence while preserving the live tool
  result returned to callers

## Consequences

- The pipeline is now auditable by trace alone because every required stage is
  explicit and ordered.
- Hook authors get a stable typed state object instead of an unstructured
  kwargs bag.
- Duplicate receipt emission for the same attempt/result tuple is suppressed in
  the pipeline itself, which keeps this bounded slice safe even before wider
  receipt integration lands elsewhere.
- Existing executors stay unchanged; they can adopt the serial adapter or the
  `begin`/`complete` split later.
- Evidence is safer for remote/provider-backed tools because redacted payloads
  are persisted while the live result remains intact for the conversation loop.

## Alternatives considered

- Expanding the old hook runner in place without typed state. Rejected because
  it would keep metadata defaults and blocked/error flows implicit.
- Refactoring existing tool executors in the same change. Rejected because the
  bounded slice explicitly forbids editing those workers.
- Writing receipts outside the pipeline. Rejected for this slice because it
  would leave duplicate-attempt suppression unsolved where the attempt context
  actually exists.
