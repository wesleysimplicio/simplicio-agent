# ADR-0017: Cognitive Integrity Boundary

## Status

Accepted - 2026-07-13

## Context

Issue #185 needs a bounded trust-boundary slice that can reject forged control
signals and tampered receipts without widening the core tool or transport
surface. The scope here is limited to a local value-object module, focused
tests, and static fixtures. It must fail closed, use only stdlib/local
dependencies, and avoid touching provider, memory, browser, goal, or transport
implementations.

## Decision

We add `agent/trust_boundary.py` as a narrow cognitive-integrity contract with
six behaviors:

1. Typed provenance via `TrustClass` and `ProvenanceKind`.
2. Canonical HMAC-SHA256 verification for authenticated control events.
3. Tamper-evident receipt helpers with deterministic SHA-256 digests and
   optional receipt chaining.
4. Sanitized `blocked_cognitive_integrity` outcomes that redact payloads,
   signatures, digests, and token-like values before higher layers see them.
5. Explicit fail-closed behavior on unknown keys, unsupported algorithms,
   malformed objects, mismatched digests, and broken receipt chains.
6. Strict schema, digest, provenance-kind, and JSON-canonical-value validation;
   claimed trusted provenance cannot be created for user/tool input, and
   malformed boundary objects are converted to sanitized blocked outcomes.

## Consequences

Positive:

- The trust boundary becomes testable in isolation.
- Authenticated control-plane inputs and durable receipts have a stable,
  serializable contract.
- Blocked outcomes are safe to surface without echoing secrets or untrusted
  payloads.

Negative:

- This ADR does not yet wire the boundary into browser, transport, memory,
  provider, or goal flows.
- Receipt chaining is local and deterministic, but not yet backed by an
  external signer or hardware root of trust.
- Replay protection, timestamp freshness, and cross-session key rotation remain
  future work outside this bounded slice.

## Attack Coverage In This Slice

- Forged control event with unknown key id: denied.
- Forged control event with modified payload after signing: denied.
- Control event with unsupported digest algorithm: denied.
- Control event with an unknown schema or non-hex digest: denied.
- User/tool provenance claiming a trusted control or receipt class: denied.
- Receipt body tampering after issuance: denied.
- Broken receipt-chain predecessor digest: denied.
- Secret-bearing blocked outcomes leaking payload/signature/digest values:
  sanitized before exposure.

## Cross-Surface Gaps Left Open

- Runtime/CLI/MCP integration still needs explicit call sites.
- No freshness window or anti-replay nonce store exists yet.
- No persistent receipt ledger or database-backed audit chain exists yet.
- No transport-auth binding or user-intent binding is enforced yet.
