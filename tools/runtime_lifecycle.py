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

    health_ready: bool = False
    migrations_ready: bool = False
    seed_ready: bool = False
    neural_db_ready: bool = False
    required_schemas: Mapping[str, bool] = field(default_factory=dict)
    required_capabilities: Mapping[str, bool] = field(default_factory=dict)
    optional_capabilities: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.health_ready, bool):
            raise TypeError("health_ready must be bool")
        if not isinstance(self.migrations_ready, bool):
            raise TypeError("migrations_ready must be bool")
        if not isinstance(self.seed_ready, bool):
            raise TypeError("seed_ready must be bool")
        if not isinstance(self.neural_db_ready, bool):
            raise TypeError("neural_db_ready must be bool")
        object.__setattr__(
            self,
            "required_schemas",
            _freeze_capabilities(self.required_schemas),
        )
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
    requested_min_version: str
    runtime_version: Optional[str]
    selected_source: str
    binary_resolved: bool
    binary_compatible: bool
    health_ready: bool
    migrations_ready: bool
    seed_ready: bool
    neural_db_ready: bool
    required_schemas: Mapping[str, bool]
    required_capabilities: Mapping[str, bool]
    optional_capabilities: Mapping[str, bool]
    repair_plan: tuple[str, ...]
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
            "requested_min_version": self.requested_min_version,
            "runtime_version": self.runtime_version,
            "selected_source": self.selected_source,
            "binary_resolved": self.binary_resolved,
            "binary_compatible": self.binary_compatible,
            "health_ready": self.health_ready,
            "migrations_ready": self.migrations_ready,
            "seed_ready": self.seed_ready,
            "neural_db_ready": self.neural_db_ready,
            "required_schemas": dict(self.required_schemas),
            "required_capabilities": dict(self.required_capabilities),
            "optional_capabilities": dict(self.optional_capabilities),
            "repair_plan": list(self.repair_plan),
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
                detail=status.detail or "runtime version handshake is not compatible",
            )

        if not probes.health_ready:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="runtime_health_not_ready",
                status=status,
                probes=probes,
                detail="runtime health probe is not ready",
            )

        if not probes.migrations_ready:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="migrations_not_ready",
                status=status,
                probes=probes,
                detail="runtime migrations are not ready",
            )

        if not probes.seed_ready:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="seed_not_ready",
                status=status,
                probes=probes,
                detail="runtime seed state is not ready",
            )

        if not probes.neural_db_ready:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="neural_db_not_ready",
                status=status,
                probes=probes,
                detail="neural database is not ready",
            )

        unhealthy_schemas = _unhealthy(probes.required_schemas)
        if unhealthy_schemas:
            return _result(
                phase=LifecyclePhase.NOT_READY,
                reason_code="required_schema_missing",
                status=status,
                probes=probes,
                detail="required schemas unavailable: " + ", ".join(unhealthy_schemas),
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
        requested_min_version=status.min_version,
        runtime_version=status.version,
        selected_source=status.source,
        binary_resolved=status.present,
        binary_compatible=status.satisfied,
        health_ready=probes.health_ready,
        migrations_ready=probes.migrations_ready,
        seed_ready=probes.seed_ready,
        neural_db_ready=probes.neural_db_ready,
        required_schemas=probes.required_schemas,
        required_capabilities=probes.required_capabilities,
        optional_capabilities=probes.optional_capabilities,
        repair_plan=_repair_plan(reason_code, status),
        detail=detail,
    )


def _repair_plan(reason_code: str, status: RuntimeStatus) -> tuple[str, ...]:
    if reason_code == "runtime_absent":
        return ("run `simplicio-agent doctor --fix` to install the managed runtime",)
    if reason_code == "blocked_runtime_handshake":
        return (
            "verify the selected binary is the Simplicio Runtime and rerun the handshake",
            "run `simplicio-agent doctor --fix` if the managed runtime needs reinstall",
        )
    if reason_code == "blocked_incompatible_runtime":
        plan = ["run `simplicio-agent doctor --fix` to install or update the pinned runtime"]
        if status.source in {"env", "path"}:
            plan.append(
                "remove or upgrade the user-managed runtime that is winning selection"
            )
        return tuple(plan)
    if reason_code == "runtime_health_not_ready":
        return ("restart or reconnect the managed runtime process before governed effects",)
    if reason_code == "migrations_not_ready":
        return ("apply runtime migrations before the first governed mutation",)
    if reason_code == "seed_not_ready":
        return ("complete runtime seed/bootstrap before the first governed mutation",)
    if reason_code == "neural_db_not_ready":
        return ("repair or reinitialize the neural database before governed effects",)
    if reason_code == "required_schema_missing":
        return ("negotiate the required handshake schemas before governed effects",)
    if reason_code == "required_capability_unhealthy":
        return ("restore required runtime capabilities before governed effects",)
    if reason_code == "optional_capability_unhealthy":
        return ("optional capability degraded; repair it or continue in degraded mode",)
    return ()
