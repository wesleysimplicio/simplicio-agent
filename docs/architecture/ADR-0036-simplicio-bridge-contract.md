# ADR-0036: bounded SimplicioBridge lifecycle contract

- Status: accepted for issue #222 bounded slice
- Date: 2026-07-14
- Related: ADR-0009, ADR-0020, `tools/simplicio_bridge.py`

## Context

ADR-0009 already defines the CLI-first transport and its MCP fallback. The
bridge above that boundary still needs an observable lifecycle and a bounded
retry/idempotency contract for long-lived agent processes. This slice does not
replace the transport or duplicate its fallback decision.

## Decision

`SimplicioBridge` starts in a lazy `ready` state and exposes idempotent
`start()`, `close()`, `lifecycle()`, and context-manager operations. Calls after
`close()` fail closed without invoking the transport; a subsequent `start()`
creates a new lifecycle generation. `health()` remains a backward-compatible
dictionary and includes the lifecycle plus transport/fallback evidence.

Idempotent operations use their causal id as the key. Concurrent duplicates
wait for the owner call and reuse only a successful result, while failed calls
are never cached. The cache is insertion-ordered and bounded by
`idempotency_max_entries` (1024 by default), preventing a long-lived process
from retaining every turn. `BridgeReceipt` and `BridgeLifecycle` provide
JSON-safe typed evidence without changing the legacy value-returning methods.

The transport has the same idempotent lifecycle surface. A closed transport
returns a typed `transport_closed` receipt and never invokes CLI or MCP; its
fallback event history is bounded. Runtime readiness remains read-only through
`runtime_status()`/`runtime_health()`; `doctor_status(fix=True)` is still the
only explicit repair path.

## Acceptance evidence

Focused bridge/transport tests cover closed-state fail-closed behavior,
idempotent lifecycle calls, concurrent causal-id deduplication, bounded cache
retention, typed transport-closed failure, CLI-first behavior, and the
CLI-unavailable MCP fallback. Existing #210 transport tests remain unchanged
in meaning and continue to pass.

## Non-goals and environment gap

This slice does not add core tools, wire every caller, replace shadow-git
checkpoints, or alter CLI/MCP routing. The bound `simplicio-dev-cli` operator
and mapper deep index were unavailable in the worker environment (the mapper
held a live lock without producing artifacts and the operator timed out), so
native edits were used only for this explicitly scoped contract and the gap is
reported with the verification receipts.
