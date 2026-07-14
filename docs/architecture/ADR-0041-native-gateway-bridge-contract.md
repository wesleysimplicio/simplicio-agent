# ADR-0041: bounded native gateway bridge

The native gateway bridge is a temporary compatibility seam.  It uses the
`simplicio.gateway-native/v1` request/receipt schema and a separate
`simplicio.gateway-bridge-lease/v1` lease.  A lease is issued for at most 24
hours and expiry is inclusive: at `now >= expires_at`, dispatch is rejected
before the handler can run.

`BridgeLifecycleState` is the typed, JSON-safe lifecycle projection.  It
reports `active`, `closed`, `expired`, or `rolled_back`, plus a generation and
dispatch sequence.  Requests are isolated by `bridge_id`, validated as finite
JSON, and bounded by a payload limit.  `BridgeReceipt` is the typed projection
of the existing dictionary return value, so callers can adopt typed handling
without changing the gateway's current interfaces.

Close and rollback are idempotent.  Rollback is a fail-closed marker only: the
bridge never owns restoration of legacy state, but after a rollback request it
emits a deterministic `rolled_back` receipt and never invokes the handler.
The committed fixture `fixtures/gateway/native_bridge_receipts.json` covers
the local smoke, inclusive-expiry, and rollback receipts at fixed timestamps.

This slice defines protocol and local behavior only.  Discord, CLI, and API
transport wiring, live integration, and execution of a rollback by an
updater/supervisor remain `UNVERIFIED| outside bounded gateway scope`.
