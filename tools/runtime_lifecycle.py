"""Typed, read-only lifecycle/readiness contract for the managed Runtime.

This module deliberately does not start, repair, or stop a process.  It gives
callers one deterministic projection of the existing runtime version handshake
plus the health probes they own.  In particular, a resolved binary is never
enough to report ``ready``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Optional

from .runtime_manager import RuntimeStatus, runtime_status

_HANDSHAKE_SCHEMA = "simplicio.agent-runtime-handshake/v1"


class LifecyclePhase(str, Enum):
    """Stable phases exposed by the lifecycle/readiness contract."""

    ABSENT = "absent"
    BLOCKED = "blocked"
    NOT_READY = "not_ready"
    DEGRADED = "degraded"
    READY = "ready"


@dataclass(frozen=True)
class ReadinessProbes:
    """Results owned by the Runtime health-probe implementation.

    Missing probes default to unhealthy.  This fail-closed default prevents a
    caller that only knows about the binary version from claiming readiness.
    """

    migrations_ready: bool = False
    neural_db_ready: bool = False
    required_capabilities: Mapping[str, bool] = field(default_factory=dict)
    optional_capabilities: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.migrations_ready, bool):
            raise TypeError("migrations_ready must be bool")
        if not isinstance(self.neural_db_ready, bool):
            raise TypeError("neural_db_ready must be bool")
        object.__setattr__(
            self,
            "required_capabilities",
            _freeze_capabilities(self.required_capabilities),
        )
        object.__setattr__(
            self,
            "optional_capabilities",
            _freeze_capabilities(self.optional_capabilities),
        )


@dataclass(frozen=True)
class RuntimeReadiness:
    """JSON-safe readiness result with no process or secret material."""

    schema: str
    phase: LifecyclePhase
    reason_code: str
    runtime_version: Optional[str]
    migrations_ready: bool
    neural_db_ready: bool
    required_capabilities: Mapping[str, bool]
    optional_capabilities: Mapping[str, bool]
    detail: str = ""

    @property
    def ready(self) -> bool:
        """Whether effects may use the Runtime under this contract."""
        return self.phase in {LifecyclePhase.READY, LifecyclePhase.DEGRADED}

    def as_dict(self) -> dict:
        """Return the stable wire shape used by CLI/MCP adapters."""
        return {
            "schema": self.schema,
            "phase": self.phase.value,
            "reason_code": self.reason_code,
            "runtime_version": self.runtime_version,
            "migrations_ready": self.migrations_ready,
            "neural_db_ready": self.neural_db_ready,
            "required_capabilities": dict(self.required_capabilities),
            "optional_capabilities": dict(self.optional_capabilities),
            "ready": self.ready,
            "detail": self.detail,
        }


class RuntimeLifecycleManager:
    """Compose the existing version handshake with explicit health probes.

    The default status provider is intentionally injectable so CLI, MCP, and
    tests can share this contract without coupling the probe implementation to
    process ownership or transport details.
    """

    def __init__(
        self,
        status_provider: Callable[[], RuntimeStatus] = runtime_status,
    ) -> None:
        self._status_provider = status_provider

    def readiness(
        self,
        probes: Optional[ReadinessProbes] = None,
    ) -> RuntimeReadiness:
        """Return a fail-closed readiness snapshot."""
        probes = probes or ReadinessProbes()
        status = self._status_provider()

        if not status.present:
            return _result(
                phase=LifecyclePhase.ABSENT,
                reason_code="runtime_absent",
                status=status,
                probes=probes,
                detail="runtime binary is not resolved",
            )

        if not status.satisfied:
            reason_code = (
                "blocked_incompatible_runtime"
                if status.version is not None
                else "blocked_runtime_handshake"
            )
            return _result(
                phase=LifecyclePhase.BLOCKED,
                reason_code=reason_code,
                status=status,
                probes=probes,
                detail="runtime version handshake is not compatible",
            )

        if not probes.migrations_ready:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="migrations_not_ready",
                status=status,
                probes=probes,
                detail="runtime migrations are not ready",
            )

        if not probes.neural_db_ready:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="neural_db_not_ready",
                status=status,
                probes=probes,
                detail="neural database is not ready",
            )

        unhealthy_required = _unhealthy(probes.required_capabilities)
        if unhealthy_required:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="required_capability_unhealthy",
                status=status,
                probes=probes,
                detail="required capabilities unhealthy: "
                + ", ".join(unhealthy_required),
            )

        unhealthy_optional = _unhealthy(probes.optional_capabilities)
        if unhealthy_optional:
            return _result(
                phase=LifecyclePhase.DEGRADED,
                reason_code="optional_capability_unhealthy",
                status=status,
                probes=probes,
                detail="optional capabilities unhealthy: "
                + ", ".join(unhealthy_optional),
            )

        return _result(
            phase=LifecyclePhase.READY,
            reason_code="ready",
            status=status,
            probes=probes,
        )


def _freeze_capabilities(capabilities: Mapping[str, bool]) -> Mapping[str, bool]:
    if not isinstance(capabilities, Mapping):
        raise TypeError("capabilities must be a mapping")
    normalized = {}
    for name, healthy in capabilities.items():
        if not isinstance(name, str) or not name:
            raise ValueError("capability names must be non-empty strings")
        if not isinstance(healthy, bool):
            raise TypeError("capability health must be bool")
        normalized[name] = healthy
    return MappingProxyType(normalized)


def _unhealthy(capabilities: Mapping[str, bool]) -> list[str]:
    return sorted(name for name, healthy in capabilities.items() if not healthy)


def _result(
    *,
    phase: LifecyclePhase,
    reason_code: str,
    status: RuntimeStatus,
    probes: ReadinessProbes,
    detail: str = "",
) -> RuntimeReadiness:
    return RuntimeReadiness(
        schema=_HANDSHAKE_SCHEMA,
        phase=phase,
        reason_code=reason_code,
        runtime_version=status.version,
        migrations_ready=probes.migrations_ready,
        neural_db_ready=probes.neural_db_ready,
        required_capabilities=probes.required_capabilities,
        optional_capabilities=probes.optional_capabilities,
        detail=detail,
    )
