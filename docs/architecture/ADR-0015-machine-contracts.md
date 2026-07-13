# ADR-0015: Versioned machine contracts for agent/runtime identity

- Status: accepted
- Date: 2026-07-13
- Related: issue #191

## Context

The agent and runtime are one shipped system, but they still cross a machine
boundary whenever they exchange capability, health, or receipt data. That
boundary was underspecified: older payloads were effectively shape-based,
agent-versus-runtime identity was easy to blur, and receipt metadata could
carry host-specific details that should not leak into generic ledgers or
doctor output.

This slice also had to stay out of MCP wiring, alias registries, and release
surfaces. The requirement was a narrow contract layer that other transports
can reuse without changing routing policy.

## Decision

`tools/machine_contracts.py` defines the versioned contract layer.

- `ProductIdentity` names the shipped product surface as `Simplicio Agent`.
- `ComponentIdentity` keeps the machine-facing parts separate:
  `simplicio-agent` is the orchestration component and `simplicio-runtime`
  is the deterministic kernel component.
- `SchemaProducerEnvelope` describes what schema version a component emits and
  what consumer-version window it can interoperate with.
- `upcast_legacy_contract()` adapts legacy unversioned payloads into the
  current `machine-contracts/product/v1` layout instead of keeping parallel
  readers throughout the codebase.
- `ReceiptMetadata.redacted()` produces a receipt-safe view that strips
  path-, env-, token-, and key-like fields before the metadata is attached to
  diagnostics or ledgers.
- `compatibility_report()`, `compatibility_row()`, and
  `compatibility_matrix()` provide a stable, versioned way to state whether
  an agent/runtime pair is expected to interoperate.

The contract stays transport-agnostic. CLI, MCP, warm bindings, and alias
surfaces may consume it later, but they do not own its schema.

## Consequences

- Product identity and component identity are explicit instead of implicit.
- Agent/runtime separation is preserved at the schema boundary without
  implying product separation.
- Legacy payloads are normalized once through an upcaster.
- Receipt metadata can be reused safely in doctor/evidence flows.
- Compatibility expectations become auditable and easy to fixture-test.

## Alternatives considered

- Let each transport define its own payload shape: rejected because it would
  duplicate policy and reintroduce drift between CLI and fallback paths.
- Keep legacy support as ad hoc field probes in callers: rejected because the
  compatibility burden would spread across unrelated modules.
- Collapse agent and runtime into one component identifier: rejected because
  it hides the actual machine boundary that issue #191 needs to describe.
