# ADR-0031 — Agent Mapper ContextSnapshot/ContextGraph v1 adapter

Status: proposed in issue #498

## Decision

The Agent consumes the Mapper-owned `simplicio.context-snapshot/v1` and
`simplicio.context-graph/v1` contracts through `agent.mapper_adapter`. The
adapter is read-only and uses either the installed Mapper binding or the
public `simplicio-mapper snapshot build --json` CLI. Schema validation is
delegated to the installed Mapper validator; the Agent does not copy schemas,
fixtures, or Mapper implementation details.

`ContextSnapshotHandle` carries the negotiated schema and producer identity,
repository/revision/root/config hashes, fidelity, generation time, snapshot
identity, and the `session_id`/`turn_id`/`attempt_id` causal scope. A pin is
immutable for that causal attempt: a revision or snapshot change returns
`stale/PIN_REVISION_CHANGED`.

## Lifecycle and degradation

1. Negotiate Mapper capabilities and the v1 schema IDs.
2. Ask the selected transport for a snapshot and validate it fail-closed with
   the Mapper validator, optionally against a source root.
3. Reject incompatible schema, hash mismatch, stale revision/freshness, and
   insufficient fidelity as typed `MapperResult` states.
4. Cache only validated payloads behind a bounded, TTL-limited cache whose key
   includes repository, profile, revision, config hash, producer version, and
   snapshot content identity.
5. Resolve graph nodes/edges and expand only requested handles/scales within
   explicit node/edge budgets. A budget miss is `insufficient_context`; it does
   not trigger a repository-wide reread.
6. Refresh/revalidate through the selected transport. Invalidation removes
   cached materialization while preserving the pin invariant.

Supported states are `available`, `unavailable`, `timeout`,
`incompatible_schema`, `stale`, `insufficient_context`, `fidelity_rejected`,
and `tampered`. No state silently falls back to broad source reads.

## Security and observability

Source handles remain Mapper-owned reversible references. The adapter returns
handles and graph rows, never copies source content. Validation enforces the
Mapper's path, payload, depth, fidelity, and digest rules. Optional adapter
events contain only causal IDs, status/reason code, latency, byte counts,
cache-hit state, materialized counts, and fallback reason; they do not contain
paths, source text, secrets, or raw payloads.

The contract manifest digest can be pinned by the caller. Compatibility is
version-gated at the declared Mapper floor (`0.24.1`); future or unknown
transport capability is rejected rather than guessed. TurnEngine integration
is intentionally left to the child wiring issue.
