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
- the sequential executor did not close its invocation with the shared
  receipt/evidence pipeline
- external results could be copied verbatim into evidence payloads
- split traces could lose the persist/evidence tail when execute was omitted
- finalization hook failures could leave a terminal attempt without evidence

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
- canonical trace completion preserves the bounded terminal tail (`persist`,
  `evidence`) even when a split caller omits `execute`
- receipt identity is scoped to `attempt_id`, so a replayed completion cannot
  emit a second receipt for the same attempt even if its result or status differs
- persist, evidence, receipt-writer, and cancellation failures are terminalized
  as error/cancelled outcomes without rerunning a side-effecting persist hook
- serial adapters remain synchronous, copy the top-level argument mapping, and
  fall back to the `serial` executor label when callers provide an empty label
- unknown metadata/status values resolve to conservative defaults (`pending`
  before execution and `error` for an invalid terminal status)
- sequential and special-tool dispatches begin and complete the same pipeline
  used by the concurrent adapter; scheduler selection remains unchanged
- a required checkpoint with no checkpoint hook, or an explicit checkpoint
  denial, blocks before execution and still emits a receipt/evidence record
- `default_tool_invocation_receipt_writer` stores only serialized provenance
  and args/result hashes through the existing content-addressed receipt ledger

## Consequences

- The pipeline is now auditable by trace alone because every required stage is
  explicit and ordered.
- Hook authors get a stable typed state object instead of an unstructured
  kwargs bag.
- Duplicate receipt emission for the same attempt/result tuple is suppressed in
  the pipeline itself, which keeps this bounded slice safe even before wider
  receipt integration lands elsewhere.
- Tool-specific implementations and scheduler selection stay unchanged; the
  sequential executor adopts the `begin`/`complete` split at its dispatch
  boundary.
- Its display, middleware, and tool-specific branches remain in place, while
  concurrent and DAG routing remain behaviorally unchanged.
- Evidence is safer for remote/provider-backed tools because redacted payloads
  are persisted while the live result remains intact for the conversation loop.
- A receipt writer failure is fail-safe: the local receipt remains attached for
  diagnostics, `receipt_written` stays false, and evidence records the writer
  exception instead of claiming a successful persistence.

## Alternatives considered

- Expanding the old hook runner in place without typed state. Rejected because
  it would keep metadata defaults and blocked/error flows implicit.
- Refactoring existing tool executors in the same change. Rejected because the
  bounded slice explicitly forbids editing those workers.
- Writing receipts outside the pipeline. Rejected for this slice because it
  would leave duplicate-attempt suppression unsolved where the attempt context
  actually exists.
