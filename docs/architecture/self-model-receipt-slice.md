# Bounded self-model receipt slice (#168)

Status: implemented as a pure contract layer; integration remains a follow-up.

`agent.self_model` materializes a profile/tenant-scoped `simplicio.self-model/v1`
snapshot from authoritative capability, health, policy, and budget receipts supplied
by existing callers.  It deliberately does not discover capabilities, grant
authority, modify the cached tool schema, or add a new UI surface.

The contract separates `installed`, `configured`, `healthy`, `authorized`, and
`verified`.  A verified actuator must name both a verifier and rollback reference;
an authorized actuator must carry an owner scope.  Authority can only be
attenuated, never escalated, and every state update adds a measured/canonical
source receipt.  Tool/page output is rejected as a health authority and
secret-like identifiers are rejected at serialization boundaries.

`SelfModelSnapshot.transition()` provides the focused loss/recovery seam used by
future registry and runtime-health adapters.  It returns a typed
`capability_loss`/`capability_recovery` transition and updates degraded modalities
without changing tool schemas or executing an effect.

Focused evidence:

```text
python -m pytest tests/agent/test_self_model.py -q
```

Non-goals and external gaps: no registry/Runtime/health source adapter, no
planner/UI integration, no device/window broker, and no clean-machine or
cross-surface E2E. Those require the upstream #148/#159 boundaries and should
be implemented as separate slices.
