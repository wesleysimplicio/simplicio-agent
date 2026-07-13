# ADR-0009: CLI-first Simplicio transport boundary

*Status: Accepted — 2026-07-13*

## Context

The agent has several kernel bindings and needs one observable boundary for
execution, evidence, and diagnostics. The routing hierarchy is canonical in
[`AGENTS.md#tool-routing`](../../AGENTS.md#tool-routing); this ADR records the
transport contract rather than restating that hierarchy.

## Decision

`tools.simplicio_transport.SimplicioTransport` is the default transport used
by `SimplicioBridge`. It executes one `simplicio <command>` subprocess per
call and returns a `simplicio-transport/receipt/v1` receipt. Errors use the
`simplicio-transport/error/v1` shape (`code`, `message`, and `retryable`) so
callers do not need operation-specific exception parsing.

MCP fallback is permitted only for CLI unavailability: no resolved executable
or a process launch failure. A command exit failure, timeout, malformed JSON,
or policy error is a CLI receipt and does not invoke MCP. Fallback receipts
carry `fallback_reason: "cli_unavailable"`; the transport also emits a
`simplicio-transport/fallback/v1` ledger event when a ledger callback is
configured. This preserves the reason an operation used MCP even when the
operation itself succeeded.

The bridge retains its typed value methods for existing callers and exposes
the transport health snapshot under `health()["transport"]`. Runtime
dependency health and the explicit repair report are provided by
`runtime_manager.runtime_health()` and `runtime_manager.doctor_status()`;
neither performs installation unless `doctor_status(fix=True)` is requested.

## Consequences

* CLI behavior is deterministic and testable without an MCP dependency.
* MCP cannot mask an executed CLI command's error or silently change retry
  semantics.
* Receipts make transport choice, fallback reason, and error evidence
  available to health/doctor surfaces and future callers.
* The existing kernel bindings remain compatible; this boundary does not
  duplicate kernel logic or change the conversation prompt/tool schema.
