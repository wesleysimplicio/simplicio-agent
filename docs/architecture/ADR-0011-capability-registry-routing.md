# ADR-0011: Deterministic capability registry and routing

- Status: accepted
- Date: 2026-07-13
- Related: issue #148

## Context

The agent has several capability/provider registries, but they expose
different metadata and leave fallback behavior to their callers.  That makes
the same request choose different implementations depending on registration
order, and a capability can change halfway through a session.  Operators also
need an actionable reason when a capability is unavailable instead of a
generic failure.

## Decision

`agent/capability_registry.py` defines the narrow, transport-neutral policy
surface `CapabilityRegistry`.  Every `Capability` carries immutable metadata
for version, source, license, supported platforms, health, risk,
determinism, and estimated cost.  Registry registration is explicit and
duplicate names are rejected.

Fallback order is the requested capability followed by its `fallback` tuple,
in exactly that order.  Routing never sorts by health, cost, risk, or
registration order.  A missing, incompatible, unhealthy, too-expensive, or
policy-blocked candidate produces a stable `ReasonCode`; the returned
`attempted` tuple is the audit trail for the decision.

Risky and nondeterministic capabilities require explicit caller consent.
Health or policy failures may provide a `RepairPlan`, but every repair plan
is marked `requires_consent=True` and is informational until a higher-level
owner obtains consent and performs the repair.  The registry does not perform
I/O, authentication, installation, or transport calls.

When a route succeeds with a `session_id`, the selected capability and version
are pinned.  Later routes in that session return the pinned candidate even if
the request names a fallback alias.  If the pinned candidate disappears or
changes version, routing returns `PINNED_CAPABILITY_UNAVAILABLE` instead of
silently switching.  The session owner may explicitly unpin and route again.

## Consequences

- Route decisions are deterministic and straightforward to replay.
- Metadata is available to policy, diagnostics, and future catalog adapters
  without coupling this slice to transport or prompt code.
- A session cannot silently move to another implementation after selection.
- Repair remains an explicit, consent-gated operation owned by the caller.
- Runtime health can be updated by replacing a capability record; existing
  session pins still protect the session from an implicit version change.

## Alternatives considered

- **Weighted or score-based routing:** rejected because changing telemetry or
  cost values would change behavior without a policy change and would make
  replay difficult.
- **Automatic repair:** rejected because installation, reauthentication, and
  source changes have external side effects and require user consent.
- **Registry-order fallback:** rejected because import/discovery order is not a
  durable policy and varies across surfaces.
- **Transport-owned metadata:** rejected because transport modules would then
  duplicate policy and make the capability contract unavailable to local or
  deterministic callers.
