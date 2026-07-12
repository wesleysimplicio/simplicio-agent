"""Distributed node host package.

Materialized from ADR-0006 (``docs/adr/0006-distributed-node-host.md``) and
``docs/distributed/overview.md`` in ``wesleysimplicio/hermes-turbo-agent``.

This iteration ships the **wire-protocol type contract only** (``protocol.py``).
The gateway and node runtime are deferred to the prototype plan in ADR-0006 and
do not exist yet, so there is nothing to import-side-effect here. The control
plane imports these dataclasses to build ``TaskDispatch`` envelopes; the node
plane builds ``NodeRegister`` / ``TaskResult`` / ``HealthPing``.

Nothing in this package touches the model-facing agent loop, prompt assembly,
or the prompt-cache stable prefix, so it cannot invalidate per-conversation
prompt caching.
"""

from .protocol import (
    AgentTerms,
    CapabilitySpec,
    HealthPing,
    NodeHealthState,
    NodeRegister,
    PROTOCOL_VERSION,
    TaskDispatch,
    TaskResult,
    TaskStatus,
    WIRE_TYPES,
    HEALTH_DEGRADED_MISSING,
    HEALTH_EVICTED_MISSING,
    HEALTH_PING_INTERVAL_S,
    is_protocol_compatible,
    node_health_state,
    protocol_major,
)

__all__ = [
    "AgentTerms",
    "CapabilitySpec",
    "HealthPing",
    "HEALTH_DEGRADED_MISSING",
    "HEALTH_EVICTED_MISSING",
    "HEALTH_PING_INTERVAL_S",
    "NodeHealthState",
    "NodeRegister",
    "PROTOCOL_VERSION",
    "TaskDispatch",
    "TaskResult",
    "TaskStatus",
    "WIRE_TYPES",
    "is_protocol_compatible",
    "node_health_state",
    "protocol_major",
]
