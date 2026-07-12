# Integration notes — `agent/distributed`

Ported from `wesleysimplicio/hermes-turbo-agent` per **ADR-0006** (and the
tracking issue #97). Source repo state at port time: the `hermes-turbo-agent`
repository contained **only the ADR document and a plan** for the distributed
node host — there was **no `agent/distributed/` implementation** (the PR that
was meant to ship the `protocol.py` skeleton was reopened because "previous
closure had no commits"). This module therefore *materializes the ADR contract*
into real, typed, round-trippable dataclasses rather than copying existing code.
The contract is taken verbatim from:

- `docs/adr/0006-distributed-node-host.md` (authoritative wire types, auth,
  capability addressing, failover)
- `docs/distributed/overview.md` (dataclass shape, `PROTOCOL_VERSION`, ping
  thresholds)

## What this module is

A self-contained **type contract**. Four msgspec-friendly frozen dataclasses
(`NodeRegister`, `TaskDispatch`, `TaskResult`, `HealthPing`) plus the capability
addressing record (`CapabilitySpec`) with its **mandatory** `AgentTerms`
guardrails, a `PROTOCOL_VERSION` with a major-mismatch compat check, and the
`HealthPing` degraded/evicted thresholds (3 / 6 missed pings).

## Integration surface (intentionally minimal)

This module is **pure types + validation** — it performs no IO, spawns nothing,
and never touches the model-facing agent loop, `run_agent.py`,
`hermes_cli/daemon.py`, or `gateway/run.py`. Therefore the **smallest safe
integration is: none yet.**

No shared file was modified. The prototype plan (ADR-0006 section "Prototype
plan") lands the gateway (`agent/distributed/gateway.py`) and node runtime
(`agent/distributed/node_runtime.py`) in follow-up PRs; only at that point does
a single isolated call site in the control plane need to construct
`TaskDispatch` envelopes from this package. Until then, importing
`agent.distributed` is a no-op with respect to the rest of the codebase.

### Future hook (do NOT implement now)

When the gateway lands, the isolated touch-point will be:

```python
from agent.distributed import TaskDispatch, TaskStatus, NodeRegister
```

used only inside the control plane's tool-dispatch path, with the explicit
guarantee that the agent loop **never imports node code and never calls
`subprocess.Popen`** (ADR-0006 isolation property). The prompt-cache stable
prefix (ADR-0005) is unaffected because these types carry no conversation
history.

## Risks to reconcile on the real port

- **No upstream code existed.** This is the only risk. The shapes are derived
  from the ADR, not from a reviewed implementation; when turbo actually lands
  `protocol.py`, diff these dataclasses against it and reconcile field names /
  defaults. The ADR is the source of truth until then.
- **`msgspec` dependency.** Wire format is msgspec-encoded JSON. `msgspec` is
  already a declared dependency of `simplicio-agent` (`pyproject.toml`), so no
  new dependency is introduced. The dataclasses are plain
  `@dataclass(slots=True, frozen=True)` and remain importable without msgspec;
  only (de)serialization needs it.
- **Python version.** `slots=True` requires Python >= 3.10; the repo targets
  `>=3.11`, consistent here.
- **Capability validation is strict by design.** `AgentTerms` and
  `CapabilitySpec` raise on construction; a malformed `NodeRegister` is rejected
  at registration exactly as ADR-0006 requires. Tests assert both the accept and
  reject paths.
