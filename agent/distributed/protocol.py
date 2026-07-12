"""Distributed node host wire protocol.

This module is the **authoritative type contract** for the Hermes distributed
node host, materialized from :rfc:`ADR-0006` (``docs/adr/0006-distributed-node-host.md``)
and ``docs/distributed/overview.md`` in ``wesleysimplicio/hermes-turbo-agent``.

The architecture splits a single agent loop into two planes joined by a gateway:

* **Control plane** -- the model-facing agent loop. Emits ``TaskDispatch``
  envelopes, consumes ``TaskResult``. Never imports node code, never spawns a
  subprocess.
* **Node plane** -- one or more *nodes*, each registered with a typed capability
  set, living on the surface that owns the capability (desktop, car head-unit,
  phone, headless browser pod).
* **Gateway** -- the only thing the control plane talks to. Multiplexes nodes,
  persists pairing state, enforces approval, and exposes one
  ``dispatch / result / health`` surface regardless of node count.

Implementation status (per ADR-0006): this PR ships the **dataclass skeletons
only**; gateway/node_runtime transport is deferred to the prototype plan (steps
2-4). No network code exists yet. What *is* defined here, and is load-bearing:

* The four message types (``NodeRegister``, ``TaskDispatch``, ``TaskResult``,
  ``HealthPing``) as ``@dataclass(slots=True, frozen=True)`` so they are
  msgspec-friendly (wire format: msgspec-encoded JSON over a single long-lived
  bidirectional stream).
* The capability addressing record (``CapabilitySpec``) and its mandatory
  ``agent_terms`` guardrails (``cpu_quota_pct``, ``disk_quota_mb``) -- a node
  that registers a capability without them is rejected at ``NodeRegister``.
* ``PROTOCOL_VERSION`` and a major-mismatch compatibility check, rejected at
  registration.
* The HealthPing liveness thresholds (3 consecutive misses -> degraded,
  6 -> evicted) plus a pure helper to derive node state from a miss count.

Nothing here mutates agent context or the prompt-cache stable prefix, so the
"per-conversation prompt caching is sacred" invariant is untouched.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Literal

# --------------------------------------------------------------------------
# Protocol versioning
# --------------------------------------------------------------------------
# Wire format (msgspec JSON) is allowed to change transport freely; the payload
# schema is not. ``PROTOCOL_VERSION`` is a semver string; only a *major*
# mismatch is rejected at registration (minor/patch are additive/compatible).
PROTOCOL_VERSION: str = "1.0"


def protocol_major(version: str) -> str:
    """Return the major component of a ``major.minor.patch`` version string."""
    return version.split(".", 1)[0]


def is_protocol_compatible(peer_version: str) -> bool:
    """True when ``peer_version`` shares our major version.

    A major mismatch means a breaking payload-schema change and must be
    rejected at ``NodeRegister`` (ADR-0006 section 2).
    """
    if not peer_version:
        return False
    return protocol_major(peer_version) == protocol_major(PROTOCOL_VERSION)


# --------------------------------------------------------------------------
# HealthPing liveness thresholds
# --------------------------------------------------------------------------
# Overview: a node missing 3 consecutive pings (default 9s wall at a 3s cadence)
# is marked *degraded*; 6 consecutive misses evicts it and its in-flight tasks
# fan out to sibling nodes (or return ``status=timeout``).
HEALTH_PING_INTERVAL_S: float = 3.0
HEALTH_DEGRADED_MISSING: int = 3
HEALTH_EVICTED_MISSING: int = 6

NodeHealthState = Literal["healthy", "degraded", "evicted"]


def node_health_state(consecutive_misses: int) -> NodeHealthState:
    """Derive a node's health state from its count of consecutive missed pings.

    Pure function -- no IO, no agent state. Mirrors the failover state machine
    in ADR-0006 section 5 / overview "Failover".
    """
    if consecutive_misses >= HEALTH_EVICTED_MISSING:
        return "evicted"
    if consecutive_misses >= HEALTH_DEGRADED_MISSING:
        return "degraded"
    return "healthy"


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class TaskStatus(str, Enum):
    """Outcome of a dispatched task, returned in ``TaskResult.status``.

    ``ok`` -- executed successfully.
    ``error`` -- node-side failure (see ``TaskResult.error``).
    ``timeout`` -- exceeded ``TaskDispatch.deadline_s`` (or node evicted).
    ``denied`` -- approval/auth gate rejected the dispatch.
    """

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    DENIED = "denied"


# --------------------------------------------------------------------------
# Capability addressing (yool / tuple / HAMT)
# --------------------------------------------------------------------------
@dataclasses.dataclass(slots=True, frozen=True)
class AgentTerms:
    """Mandatory per-capability guardrails (yool spec sections 11.1 / 11.2).

    A node that registers a capability without ``cpu_quota_pct`` and
    ``disk_quota_mb`` is **rejected at NodeRegister**. ``timeout_s`` is optional.
    """

    cpu_quota_pct: int  # MANDATORY -- percent of one core, spec 11.1
    disk_quota_mb: int  # MANDATORY -- megabytes, spec 11.2
    timeout_s: int | None = None

    def __post_init__(self) -> None:
        if self.cpu_quota_pct is None or self.disk_quota_mb is None:
            raise ValueError(
                "AgentTerms.cpu_quota_pct and disk_quota_mb are mandatory "
                "per the yool spec; a capability without them is rejected at "
                "NodeRegister."
            )
        if not 0 <= self.cpu_quota_pct <= 100:
            raise ValueError(f"cpu_quota_pct out of range: {self.cpu_quota_pct}")
        if self.disk_quota_mb < 0:
            raise ValueError(f"disk_quota_mb must be >= 0: {self.disk_quota_mb}")
        if self.timeout_s is not None and self.timeout_s < 0:
            raise ValueError(f"timeout_s must be >= 0: {self.timeout_s}")


@dataclasses.dataclass(slots=True, frozen=True)
class CapabilitySpec:
    """A single typed capability registered by a node.

    ``yool_id`` addresses the capability, e.g. ``capability.desktop.system.run``.
    ``authority`` is one of ``dev | ops | review | audit``; ``lane`` is one of
    ``fast | slow | background``.
    """

    yool_id: str
    authority: str  # dev | ops | review | audit
    lane: str  # fast | slow | background
    agent_terms: AgentTerms

    _VALID_AUTHORITY = ("dev", "ops", "review", "audit")
    _VALID_LANE = ("fast", "slow", "background")

    def __post_init__(self) -> None:
        if not self.yool_id:
            raise ValueError("CapabilitySpec.yool_id is required")
        if self.authority not in self._VALID_AUTHORITY:
            raise ValueError(
                f"authority must be one of {self._VALID_AUTHORITY}, got "
                f"{self.authority!r}"
            )
        if self.lane not in self._VALID_LANE:
            raise ValueError(
                f"lane must be one of {self._VALID_LANE}, got {self.lane!r}"
            )


# --------------------------------------------------------------------------
# Wire message types
# --------------------------------------------------------------------------
@dataclasses.dataclass(slots=True, frozen=True)
class NodeRegister:
    """Node -> gateway. Declares identity, surface, capabilities, auth, version.

    Sent on connect and on every capability change (ADR-0006 section 2).
    """

    node_id: str
    surface: str  # desktop | car | mobile | browser-pod | ...
    capabilities: list[CapabilitySpec]
    auth_token: str  # long-lived, revocable, scoped to one gateway
    protocol_version: str  # must be major-compatible with PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("NodeRegister.node_id is required")
        if not is_protocol_compatible(self.protocol_version):
            raise ValueError(
                f"protocol_version {self.protocol_version!r} is incompatible "
                f"with gateway PROTOCOL_VERSION {PROTOCOL_VERSION!r} (major "
                f"mismatch is rejected at registration)"
            )


@dataclasses.dataclass(slots=True, frozen=True)
class TaskDispatch:
    """Control plane -> gateway -> node. Carries one task to execute.

    ``payload`` is arbitrary (kept as ``Any`` for msgspec round-tripping);
    **secrets never travel in ``payload``** -- credentials are referenced by
    alias and resolved by the node's local keystore (ADR-0006 section 3).
    """

    task_id: str
    capability: str  # yool id, e.g. capability.desktop.system.run
    payload: Any
    approval_token: str | None  # required for sensitive capabilities
    deadline_s: float  # wall-clock budget; exceeded -> TaskResult.timeout
    idempotency_key: str  # dedup key for at-least-once delivery

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("TaskDispatch.task_id is required")
        if not self.capability:
            raise ValueError("TaskDispatch.capability is required")
        if self.deadline_s <= 0:
            raise ValueError(f"deadline_s must be > 0: {self.deadline_s}")


@dataclasses.dataclass(slots=True, frozen=True)
class TaskResult:
    """Node -> gateway -> control plane. Outcome of a dispatched task."""

    task_id: str
    status: TaskStatus  # ok | error | timeout | denied
    result_payload: Any
    error: str | None  # populated when status == error
    elapsed_ms: float
    node_id: str

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("TaskResult.task_id is required")
        if not isinstance(self.status, TaskStatus):
            raise ValueError(
                f"TaskResult.status must be a TaskStatus, got {self.status!r}"
            )
        if self.status is TaskStatus.ERROR and not self.error:
            raise ValueError("TaskResult.error is required when status == error")


@dataclasses.dataclass(slots=True, frozen=True)
class HealthPing:
    """Bidirectional liveness + load signal. Drives failover (ADR-0006 section 5)."""

    node_id: str
    ts: float  # epoch seconds
    inflight_count: int
    cpu_pct: float
    mem_pct: float
    disk_pct: float

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("HealthPing.node_id is required")
        if self.inflight_count < 0:
            raise ValueError(
                f"inflight_count must be >= 0: {self.inflight_count}"
            )


# Backwards/forwards convenience: the full set of wire types, in registration
# order, so transport code can ``import`` them in one place.
WIRE_TYPES = (NodeRegister, TaskDispatch, TaskResult, HealthPing)
