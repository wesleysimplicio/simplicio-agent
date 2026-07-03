# ADR-0002: Provider-mode contract — 3 modes of operation

- Status: accepted
- Date: 2026-07-03
- Related: issue #64, issue #65 (MCP telemetry), simplicio-runtime#2780 (MCP daemon), #18 (epic)

## Context

The Simplicio Agent serves in three roles with the **same binary**:

1. **Autonomous agent** — like the original Hermes behavior, someone opens CLI/gateway
   and the agent operates from reasoning to delivery.
2. **Deterministic arm** of any frontier LLM that calls it via MCP — discrete,
   deterministic operations only (map, edit, gate, test, evidence).
3. **Delegated loop** — an external LLM hands over a full task and the agent runs
   its loop with optional caller-provided credentials.

Before this ADR, the agent only had the autonomous mode, and the `call_llm` chokepoint
always resolved its own provider. The MCP daemon (simplicio-runtime#2780) introduced
the possibility of external LLMs invoking the agent, which requires an explicit
**contract** for how the provider is resolved in each context.

## Decision

We define three explicit **provider modes** resolved deterministically by the
invocation origin. The single decision point is `resolve_provider_mode()` in
`agent/provider_mode.py`.

### The three modes

| Mode | Invocation origin | LLM calls inside agent? | Provider used | Cost attribution |
|------|------------------|------------------------|---------------|------------------|
| **standalone** | CLI/gateway (non-MCP) | Yes (full loop) | Own provider (`~/.simplicio/`) | Agent pays |
| **tool** | MCP request without `provider_ref` | **No** — determinism by contract | Provider kept cold | Agent pays (deterministic ops are cheap) |
| **delegated** | MCP request with explicit `provider_ref` | Yes (full loop) | Caller's provider if gated, else local ladder | Caller pays if provider_ref passed |

### Resolution rules

```python
if not origin.is_mcp:
    return ProviderMode.STANDALONE
if origin.has_provider_ref:
    return ProviderMode.DELEGATED
return ProviderMode.TOOL
```

This is the single decision point — every code path converges here.

### Credential safety (non-negotiable)

"Operate with the provider of the caller" has two faces:

- **Good:** cost attribution (caller pays own tokens, same model family)
- **Dangerous:** credential harvesting (an MCP server that captures LLM keys)

**Contract:**

1. The caller's credential enters by **explicit `provider_ref`** in the MCP request.
2. It passes through **Action Gate (`classify`)** before any use.
3. It is used **only in that session** — never persisted to disk/config.
4. It is **redacted** from all logs/evidence (reuses existing secret redaction from `agent/redact.py`).
5. Without explicit `provider_ref` → delegated mode uses local ladder, period.

The `CallContract` dataclass encodes these invariants:

- `assert_allowed()` raises if the contract violates the mode rules.
- `gate_llm_call()` gates through Action Gate, with optional auto-fallback to local ladder.
- `to_dict()` redacts `provider_ref` when the `redacted` flag is set.

### Cost attribution

The `CallContract.cost_attribution` field records who bears the cost:

- `"agent"` — the operator of this agent instance pays (standalone mode,
  tool mode, or delegated with local ladder fallback).
- `"caller"` — the external LLM/host that invoked the agent pays
  (delegated mode with gated `provider_ref`).

This field is consumed by the MCP telemetry system (issue #65) to attribute
cost in session reports.

## Consequences

- **Backward compatible:** existing standalone usage is unaffected; the new
  modes are purely additive.
- **Determinism guarantee:** tool mode raises `RuntimeError` if any code
  path attempts an LLM call, making the contract testable by assertion.
- **Security by default:** without an Action Gate, `gate_llm_call()` conservatively
  denies all `provider_ref` requests and falls back to local ladder.
- **Clear provenance:** every LLM call has a `CallContract` documenting how
  the provider was resolved, gated, and attributed.

## Alternatives considered

- **Implicit credential harvesting (rejected):** silently reading the caller's
  environment for API keys. Rejected as a security anti-pattern.
- **Two modes only (standalone + tool, no delegated) (rejected):** the delegated
  mode is the primary value proposition of the MCP daemon — an external LLM
  that can hand off entire tasks. Removing it removes the product reason for
  the MCP boundary.
- **Provider resolution via config file (rejected):** resolving mode by reading
  a config file on every invocation is slow, fragile, and breaks the prompt
  cache (config can change mid-conversation). Resolution by invocation origin
  is stateless and deterministic.