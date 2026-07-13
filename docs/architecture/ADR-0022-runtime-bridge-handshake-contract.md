# ADR-0022: typed Agent<->Runtime handshake contract slice for epic #159

- Status: accepted for this slice
- Date: 2026-07-13
- Related: epic #159, issue #162, ADR-0003, ADR-0008

## Decision

The Agent now emits a typed compatibility record,
`simplicio.agent-runtime-handshake/v1`, from `tools/runtime_manager.py` for
every health/doctor check.

This slice is intentionally narrow:

- `RuntimeStatus` keeps the existing banner/version handshake.
- Health/doctor responses now include a stable `reason_code` plus a typed
  `handshake` object instead of only free-form `detail` strings.
- The typed contract records:
  `runtime_version`, `min_runtime_version`, `bin_path`, `source`,
  `agent_protocol`, optional `runtime_protocol`, `protocol_status`,
  `capabilities`, and `repair_command`.
- Current kernels are still **banner-only**, so `runtime_protocol` is
  intentionally nullable and `protocol_status=unreported` unless a future
  runtime reports a real protocol range.

## Why this slice

Epic #159 needs a single Runtime Bridge boundary, but the current repo still
surfaces readiness mostly as text. A typed compatibility record is the smallest
real architecture step that:

- gives CLI/Desktop/TUI/gateway one shape to consume later;
- introduces durable reason codes such as
  `blocked_runtime_missing`, `blocked_runtime_handshake_failed`, and
  `blocked_incompatible_runtime`;
- keeps the current managed-runtime behavior unchanged while making drift
  machine-readable.

## Non-goals

- This does **not** claim cross-surface run projection, event replay, or
  lifecycle persistence.
- This does **not** make the runtime report protocol ranges yet; runtime-side
  support remains follow-up work under `#162`.
- This does **not** complete epic #159. It only hardens the handshake boundary
  that later slices can share.
