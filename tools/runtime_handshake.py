"""Typed Agent<->Runtime handshake contract for issue #159.

This module defines the **agent-side** handshake shape that health, doctor,
and future runtime-bridge callers consume. Current kernels still expose only a
banner-based ``--version`` handshake, so ``runtime_protocol`` remains optional
until the runtime reports it directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

HANDSHAKE_SCHEMA = "simplicio.agent-runtime-handshake/v1"
HANDSHAKE_REASON_READY = "ready"
HANDSHAKE_REASON_RUNTIME_MISSING = "blocked_runtime_missing"
HANDSHAKE_REASON_HANDSHAKE_FAILED = "blocked_runtime_handshake_failed"
HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME = "blocked_incompatible_runtime"
HANDSHAKE_PROTOCOL_STATUS_COMPATIBLE = "compatible"
HANDSHAKE_PROTOCOL_STATUS_UNREPORTED = "unreported"
DEFAULT_PROTOCOL_RANGE = (1, 1)
DEFAULT_HANDSHAKE_TTL_SECONDS = 30
MAX_HANDSHAKE_TTL_SECONDS = 300


@dataclass(slots=True, frozen=True)
class ProtocolRange:
    """Closed integer protocol range."""

    min: int
    max: int

    def __post_init__(self) -> None:
        if self.min < 0 or self.max < 0:
            raise ValueError("protocol range bounds must be >= 0")
        if self.min > self.max:
            raise ValueError(
                f"protocol range min must be <= max, got {self.min}>{self.max}"
            )

    def overlaps(self, other: "ProtocolRange") -> bool:
        return self.min <= other.max and other.min <= self.max

    def to_dict(self) -> dict[str, int]:
        return {"min": self.min, "max": self.max}


@dataclass(slots=True, frozen=True)
class CompatibilityMatrix:
    """Machine-readable preflight contract for an Agent/Runtime update."""

    agent_protocol: ProtocolRange
    runtime_protocol: ProtocolRange
    required_schemas: tuple[str, ...] = ()
    available_schemas: tuple[str, ...] = ()
    migration_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.agent_protocol, ProtocolRange):
            raise TypeError("agent_protocol must be a ProtocolRange")
        if not isinstance(self.runtime_protocol, ProtocolRange):
            raise TypeError("runtime_protocol must be a ProtocolRange")
        for name in ("required_schemas", "available_schemas", "migration_ids"):
            values = tuple(sorted({str(item).strip() for item in getattr(self, name)}))
            if any(not item for item in values):
                raise ValueError(f"{name} must contain non-empty strings")
            object.__setattr__(self, name, values)

    @property
    def missing_schemas(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.required_schemas) - set(self.available_schemas)))

    @property
    def compatible(self) -> bool:
        return self.agent_protocol.overlaps(self.runtime_protocol) and not self.missing_schemas

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_protocol": self.agent_protocol.to_dict(),
            "runtime_protocol": self.runtime_protocol.to_dict(),
            "required_schemas": list(self.required_schemas),
            "available_schemas": list(self.available_schemas),
            "missing_schemas": list(self.missing_schemas),
            "migration_ids": list(self.migration_ids),
            "compatible": self.compatible,
        }


def protocol_range_from_lock(lock: Mapping[str, Any] | None) -> ProtocolRange:
    """Read the agent-supported handshake protocol range from ``runtime.lock``."""

    raw = (lock or {}).get("handshake_protocol")
    if not isinstance(raw, Mapping):
        return ProtocolRange(*DEFAULT_PROTOCOL_RANGE)

    lower = raw.get("min", DEFAULT_PROTOCOL_RANGE[0])
    upper = raw.get("max", DEFAULT_PROTOCOL_RANGE[1])
    try:
        return ProtocolRange(int(lower), int(upper))
    except (TypeError, ValueError):
        return ProtocolRange(*DEFAULT_PROTOCOL_RANGE)


@dataclass(slots=True, frozen=True)
class RuntimeHandshake:
    """JSON-safe compatibility record for the Agent->Runtime boundary."""

    runtime_version: str | None
    min_runtime_version: str
    bin_path: str | None
    source: str
    healthy: bool
    reason_code: str
    reason_detail: str
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    agent_protocol: ProtocolRange = field(
        default_factory=lambda: ProtocolRange(*DEFAULT_PROTOCOL_RANGE)
    )
    runtime_protocol: ProtocolRange | None = None
    capabilities: tuple[str, ...] = ()
    repair_command: str = "simplicio-agent doctor --fix"
    schema: str = HANDSHAKE_SCHEMA

    def __post_init__(self) -> None:
        issued_at = _normalize_utc(self.issued_at, name="issued_at")
        expires_at = (
            issued_at + timedelta(seconds=DEFAULT_HANDSHAKE_TTL_SECONDS)
            if self.expires_at is None
            else _normalize_utc(self.expires_at, name="expires_at")
        )
        if expires_at <= issued_at:
            raise ValueError("expires_at must be later than issued_at")
        if expires_at - issued_at > timedelta(seconds=MAX_HANDSHAKE_TTL_SECONDS):
            raise ValueError(
                "handshake validity window must not exceed "
                f"{MAX_HANDSHAKE_TTL_SECONDS} seconds"
            )
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)

    @property
    def protocol_status(self) -> str:
        if self.runtime_protocol is None:
            return HANDSHAKE_PROTOCOL_STATUS_UNREPORTED
        if self.agent_protocol.overlaps(self.runtime_protocol):
            return HANDSHAKE_PROTOCOL_STATUS_COMPATIBLE
        return HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME

    def is_fresh(self, *, at: datetime | None = None) -> bool:
        """Return whether this receipt is valid at the supplied UTC instant."""

        instant = _normalize_utc(
            at if at is not None else datetime.now(timezone.utc),
            name="at",
        )
        expires_at = self.expires_at
        assert expires_at is not None
        return self.issued_at <= instant < expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "runtime_version": self.runtime_version,
            "min_runtime_version": self.min_runtime_version,
            "bin_path": self.bin_path,
            "source": self.source,
            "healthy": self.healthy,
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
            "issued_at": _format_utc(self.issued_at),
            "expires_at": _format_utc(self.expires_at),
            "agent_protocol": self.agent_protocol.to_dict(),
            "runtime_protocol": (
                self.runtime_protocol.to_dict()
                if self.runtime_protocol is not None
                else None
            ),
            "protocol_status": self.protocol_status,
            "capabilities": list(self.capabilities),
            "repair_command": self.repair_command,
        }


def build_runtime_handshake(
    *,
    lock: Mapping[str, Any] | None,
    runtime_version: str | None,
    min_runtime_version: str,
    bin_path: str | None,
    source: str,
    healthy: bool,
    reason_code: str,
    reason_detail: str,
    runtime_protocol: ProtocolRange | None = None,
    capabilities: tuple[str, ...] = (),
    issued_at: datetime | None = None,
    ttl_seconds: int = DEFAULT_HANDSHAKE_TTL_SECONDS,
) -> RuntimeHandshake:
    """Build the typed handshake emitted by runtime-manager surfaces."""

    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or not 1 <= ttl_seconds <= MAX_HANDSHAKE_TTL_SECONDS
    ):
        raise ValueError(
            "ttl_seconds must be an integer between 1 and "
            f"{MAX_HANDSHAKE_TTL_SECONDS}"
        )
    issued_at = _normalize_utc(
        issued_at if issued_at is not None else datetime.now(timezone.utc),
        name="issued_at",
    )

    return RuntimeHandshake(
        runtime_version=runtime_version,
        min_runtime_version=min_runtime_version,
        bin_path=bin_path,
        source=source,
        healthy=healthy,
        reason_code=reason_code,
        reason_detail=reason_detail,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=ttl_seconds),
        agent_protocol=protocol_range_from_lock(lock),
        runtime_protocol=runtime_protocol,
        capabilities=capabilities,
    )


def _normalize_utc(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = [
    "CompatibilityMatrix",
    "DEFAULT_HANDSHAKE_TTL_SECONDS",
    "DEFAULT_PROTOCOL_RANGE",
    "HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME",
    "HANDSHAKE_SCHEMA",
    "MAX_HANDSHAKE_TTL_SECONDS",
    "ProtocolRange",
    "RuntimeHandshake",
    "build_runtime_handshake",
    "protocol_range_from_lock",
]
