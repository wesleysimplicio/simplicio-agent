# ADR-0024: bounded native gateway bridge

The native gateway bridge is a temporary compatibility seam.  It uses the
`simplicio.gateway-native/v1` request/receipt schema and a separate
`simplicio.gateway-bridge-lease/v1` lease.  A lease is issued for at most 24
hours and expiry is inclusive: at `now >= expires_at`, dispatch is rejected
before the handler can run.

Requests are isolated by `bridge_id`, validated as JSON, and bounded by a
payload limit.  Close is idempotent; after close or expiry the bridge fails
closed and emits a JSON-safe receipt without executing legacy code.  This
slice defines protocol and local behavior only; transport wiring belongs to a
later gateway integration.
