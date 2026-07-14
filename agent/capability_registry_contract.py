"""Bounded, additive contract for capability discovery and selection.

This module deliberately does not install, download, invoke, or mutate a
capability.  It provides typed metadata, deterministic precedence, explainable
unavailability, and state needed by a caller that owns those side effects.
Keeping the contract standalone lets existing registries and tool schemas
remain session-pinned while a future adapter integrates this surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from threading import RLock
from time import monotonic
from types import MappingProxyType
from typing import Callable, Mapping


class CapabilityKind(StrEnum):
    """Kinds of capability that may be registered."""

    TOOL = "tool"
    SKILL = "skill"
    PLUGIN = "plugin"
    MCP = "mcp"
    CLI = "cli"
    PROVIDER = "provider"


class CapabilityTier(StrEnum):
    """Routing tiers, in the only order the default selector may use."""

    STRUCTURED_API_FILE_CLI = "structured_api_file_cli"
    DETERMINISTIC_RUNTIME = "deterministic_runtime"
    SKILL_PLUGIN_MCP = "skill_plugin_mcp"
    LOCAL_MODEL = "local_model"
    REMOTE_MODEL = "remote_model"
    VISUAL_COMPUTER_USE = "visual_computer_use"


DEFAULT_PRECEDENCE: tuple[CapabilityTier, ...] = (
    CapabilityTier.STRUCTURED_API_FILE_CLI,
    CapabilityTier.DETERMINISTIC_RUNTIME,
    CapabilityTier.SKILL_PLUGIN_MCP,
    CapabilityTier.LOCAL_MODEL,
    CapabilityTier.REMOTE_MODEL,
    CapabilityTier.VISUAL_COMPUTER_USE,
)
"""Stable precedence: structured -> runtime -> extensions -> models -> vision."""

_TIER_ORDER = {tier: index for index, tier in enumerate(DEFAULT_PRECEDENCE)}


class HealthStatus(StrEnum):
    """Health reported by metadata or a real, read-only health probe."""

    READY = "ready"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    """Risk policy levels, ordered from least to most sensitive."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class Determinism(StrEnum):
    """Whether a capability's result is reproducible enough for routing."""

    DETERMINISTIC = "deterministic"
    BOUNDED = "bounded"
    NON_DETERMINISTIC = "non_deterministic"


class UnavailableReasonCode(StrEnum):
    """Machine-readable reasons a capability was not selectable."""

    NOT_REGISTERED = "not_registered"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    LICENSE_NOT_ACCEPTED = "license_not_accepted"
    RISK_NOT_ACCEPTED = "risk_not_accepted"
    NON_DETERMINISTIC = "non_deterministic"
    HEALTH_CHECK_FAILED = "health_check_failed"
    CIRCUIT_OPEN = "circuit_open"


@dataclass(frozen=True)
class CapabilitySource:
    """Provenance for a capability, including an immutable source commit."""

    repository: str
    commit: str
    ref: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.repository, "source.repository")
        _require_text(self.commit, "source.commit")
        if self.ref is not None:
            _require_text(self.ref, "source.ref")


@dataclass(frozen=True)
class LicenseMetadata:
    """Separate code and weights/assets licenses for policy decisions."""

    code: str
    weights_assets: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.code, "license.code")
        if self.weights_assets is not None:
            _require_text(self.weights_assets, "license.weights_assets")


@dataclass(frozen=True)
class LatencyMetadata:
    """Measured or budgeted latency, in milliseconds."""

    p50_ms: float | None = None
    p95_ms: float | None = None

    def __post_init__(self) -> None:
        for name, value in (("p50_ms", self.p50_ms), ("p95_ms", self.p95_ms)):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.p50_ms is not None and self.p95_ms is not None:
            if self.p95_ms < self.p50_ms:
                raise ValueError("p95_ms must be greater than or equal to p50_ms")


@dataclass(frozen=True)
class CostMetadata:
    """Cost attribution kept as data; selection never charges or retries it."""

    per_call: float = 0.0
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not isfinite(self.per_call) or self.per_call < 0:
            raise ValueError("cost.per_call must be a finite non-negative number")
        _require_text(self.currency, "cost.currency")


@dataclass(frozen=True)
class CapabilityMetadata:
    """Typed, serializable metadata for one capability."""

    capability_id: str
    kind: CapabilityKind
    tier: CapabilityTier
    version: str
    source: CapabilitySource
    platforms: frozenset[str]
    license: LicenseMetadata
    health: HealthStatus = HealthStatus.UNKNOWN
    risk: RiskLevel = RiskLevel.MEDIUM
    determinism: Determinism = Determinism.BOUNDED
    latency: LatencyMetadata = field(default_factory=LatencyMetadata)
    cost: CostMetadata = field(default_factory=CostMetadata)
    schemas: Mapping[str, object] = field(default_factory=dict)
    permissions: frozenset[str] = frozenset()
    priority: int = 0

    def __post_init__(self) -> None:
        _require_text(self.capability_id, "capability_id")
        _require_text(self.version, "version")
        if not isinstance(self.kind, CapabilityKind):
            raise TypeError("kind must be a CapabilityKind")
        if not isinstance(self.tier, CapabilityTier):
            raise TypeError("tier must be a CapabilityTier")
        if not self.platforms:
            raise ValueError("platforms must contain at least one platform")
        normalized_platforms = frozenset(
            _require_text(platform, "platform").lower()
            for platform in self.platforms
        )
        if self.priority < 0:
            raise ValueError("priority must be non-negative")
        object.__setattr__(self, "platforms", normalized_platforms)
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        object.__setattr__(self, "schemas", MappingProxyType(dict(self.schemas)))


@dataclass(frozen=True)
class RepairPlan:
    """A proposed repair description; this contract never executes it."""

    steps: tuple[str, ...]
    risk: RiskLevel
    requires_consent: bool = True

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("repair plan must contain at least one step")
        for step in self.steps:
            _require_text(step, "repair step")

    def is_authorized(self, *, consent: bool, max_risk: RiskLevel) -> bool:
        """Return whether a caller may execute this plan under its policy."""

        return (
            (not self.requires_consent or consent)
            and _RISK_ORDER[self.risk] <= _RISK_ORDER[max_risk]
        )


@dataclass(frozen=True)
class UnavailableCapability:
    """Explainability receipt returned instead of silently repairing."""

    capability_id: str
    reason_code: UnavailableReasonCode
    message: str
    repair_plan: RepairPlan


@dataclass(frozen=True)
class CapabilityRequest:
    """Selection constraints supplied by a caller."""

    capability_id: str | None = None
    platform: str | None = None
    accepted_licenses: frozenset[str] | None = None
    max_risk: RiskLevel = RiskLevel.HIGH
    require_deterministic: bool = False
    require_health: bool = True

    def __post_init__(self) -> None:
        if self.capability_id is not None:
            _require_text(self.capability_id, "request.capability_id")
        if self.platform is not None:
            _require_text(self.platform, "request.platform")
            object.__setattr__(self, "platform", self.platform.lower())
        if self.accepted_licenses is not None:
            object.__setattr__(
                self,
                "accepted_licenses",
                frozenset(self.accepted_licenses),
            )


@dataclass(frozen=True)
class SelectionResult:
    """A deterministic route and all receipts needed by the caller."""

    selected: CapabilityMetadata | None
    candidates: tuple[CapabilityMetadata, ...]
    unavailable: tuple[UnavailableCapability, ...]

    @property
    def fallbacks(self) -> tuple[CapabilityMetadata, ...]:
        """Eligible candidates after the selected capability."""

        return self.candidates[1:] if self.selected is not None else ()

    @property
    def reason_code(self) -> UnavailableReasonCode | None:
        """First deterministic failure reason when nothing can be selected."""

        return self.unavailable[0].reason_code if not self.selected and self.unavailable else None


HealthProbe = Callable[[], bool | HealthStatus]


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None
    half_open_claimed: bool = False


@dataclass
class _Entry:
    metadata: CapabilityMetadata
    health_probe: HealthProbe | None
    circuit: _CircuitState = field(default_factory=_CircuitState)


class CapabilityRegistry:
    """Thread-safe metadata registry with bounded fallback selection.

    ``select`` only evaluates metadata, health probes, and breaker state.  A
    caller must invoke ``record_success`` or ``record_failure`` after its own
    single attempt; the registry never repeats an effect or a billable call.
    """

    def __init__(self, *, failure_threshold: int = 2, cooldown_seconds: float = 30.0) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if not isfinite(cooldown_seconds) or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be finite and positive")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._entries: dict[str, _Entry] = {}
        self._lock = RLock()

    def register(
        self,
        metadata: CapabilityMetadata,
        *,
        health_probe: HealthProbe | None = None,
    ) -> None:
        """Add or replace one descriptor without changing any other entry."""

        if not isinstance(metadata, CapabilityMetadata):
            raise TypeError("metadata must be a CapabilityMetadata")
        if health_probe is not None and not callable(health_probe):
            raise TypeError("health_probe must be callable")
        with self._lock:
            self._entries[metadata.capability_id] = _Entry(metadata, health_probe)

    def get(self, capability_id: str) -> CapabilityMetadata | None:
        """Return a descriptor by id, or ``None`` when it is not registered."""

        with self._lock:
            entry = self._entries.get(capability_id)
            return entry.metadata if entry else None

    def list(self) -> tuple[CapabilityMetadata, ...]:
        """Return descriptors in the same deterministic order as selection."""

        with self._lock:
            return tuple(sorted((entry.metadata for entry in self._entries.values()), key=_sort_key))

    def select(
        self,
        request: CapabilityRequest | None = None,
        *,
        now: float | None = None,
    ) -> SelectionResult:
        """Select the first eligible capability and expose ordered fallbacks."""

        request = request or CapabilityRequest()
        timestamp = monotonic() if now is None else now
        with self._lock:
            if request.capability_id is not None and request.capability_id not in self._entries:
                return SelectionResult(
                    selected=None,
                    candidates=(),
                    unavailable=(self._missing(request.capability_id),),
                )

            entries = sorted(self._entries.values(), key=lambda entry: _sort_key(entry.metadata))
            selected: list[CapabilityMetadata] = []
            unavailable: list[UnavailableCapability] = []
            for entry in entries:
                metadata = entry.metadata
                if request.capability_id is not None and metadata.capability_id != request.capability_id:
                    continue
                failure = self._eligibility_failure(entry, request, timestamp)
                if failure is not None:
                    unavailable.append(failure)
                    continue
                selected.append(metadata)

            return SelectionResult(
                selected=selected[0] if selected else None,
                candidates=tuple(selected),
                unavailable=tuple(unavailable),
            )

    def record_success(self, capability_id: str) -> None:
        """Close a circuit after the caller's one successful attempt."""

        with self._lock:
            entry = self._require_entry(capability_id)
            entry.circuit = _CircuitState()

    def record_failure(self, capability_id: str, *, now: float | None = None) -> None:
        """Count one caller-owned attempt and open after the bounded threshold."""

        timestamp = monotonic() if now is None else now
        with self._lock:
            entry = self._require_entry(capability_id)
            circuit = entry.circuit
            circuit.failures += 1
            circuit.half_open_claimed = False
            if circuit.failures >= self.failure_threshold:
                circuit.opened_at = timestamp

    def _eligibility_failure(
        self,
        entry: _Entry,
        request: CapabilityRequest,
        now: float,
    ) -> UnavailableCapability | None:
        metadata = entry.metadata
        if request.platform and "any" not in metadata.platforms and request.platform not in metadata.platforms:
            return self._unavailable(
                metadata,
                UnavailableReasonCode.PLATFORM_UNSUPPORTED,
                f"{metadata.capability_id} does not support {request.platform}",
            )
        if request.accepted_licenses is not None:
            licenses = {metadata.license.code}
            if metadata.license.weights_assets is not None:
                licenses.add(metadata.license.weights_assets)
            if not licenses.issubset(request.accepted_licenses):
                return self._unavailable(
                    metadata,
                    UnavailableReasonCode.LICENSE_NOT_ACCEPTED,
                    f"licenses for {metadata.capability_id} are outside the accepted policy",
                )
        if _RISK_ORDER[metadata.risk] > _RISK_ORDER[request.max_risk]:
            return self._unavailable(
                metadata,
                UnavailableReasonCode.RISK_NOT_ACCEPTED,
                f"risk {metadata.risk} exceeds the request policy",
            )
        if request.require_deterministic and metadata.determinism != Determinism.DETERMINISTIC:
            return self._unavailable(
                metadata,
                UnavailableReasonCode.NON_DETERMINISTIC,
                f"{metadata.capability_id} is not deterministic",
            )
        if self._breaker_is_open(entry, now):
            return self._unavailable(
                metadata,
                UnavailableReasonCode.CIRCUIT_OPEN,
                f"circuit for {metadata.capability_id} is open",
            )
        if request.require_health:
            health = metadata.health
            if entry.health_probe is not None:
                try:
                    probe_result = entry.health_probe()
                    health = (
                        probe_result
                        if isinstance(probe_result, HealthStatus)
                        else HealthStatus.READY
                        if probe_result
                        else HealthStatus.UNHEALTHY
                    )
                except Exception as exc:  # noqa: BLE001
                    health = HealthStatus.UNHEALTHY
                    message = f"health probe failed for {metadata.capability_id}: {exc}"
                else:
                    message = f"health is {health} for {metadata.capability_id}"
                if health in (HealthStatus.READY, HealthStatus.DEGRADED):
                    if entry.circuit.opened_at is not None:
                        entry.circuit = _CircuitState()
                else:
                    self._record_probe_failure(entry, now)
                    return self._unavailable(
                        metadata,
                        UnavailableReasonCode.HEALTH_CHECK_FAILED,
                        message,
                    )
            elif health not in (HealthStatus.READY, HealthStatus.DEGRADED):
                return self._unavailable(
                    metadata,
                    UnavailableReasonCode.HEALTH_CHECK_FAILED,
                    f"health is {health} for {metadata.capability_id}",
                )
        return None

    def _breaker_is_open(self, entry: _Entry, now: float) -> bool:
        circuit = entry.circuit
        if circuit.opened_at is None:
            return False
        if now - circuit.opened_at < self.cooldown_seconds:
            return True
        if circuit.half_open_claimed:
            return True
        circuit.half_open_claimed = True
        return False

    def _record_probe_failure(self, entry: _Entry, now: float) -> None:
        circuit = entry.circuit
        circuit.failures += 1
        circuit.half_open_claimed = False
        if circuit.failures >= self.failure_threshold:
            circuit.opened_at = now

    def _missing(self, capability_id: str) -> UnavailableCapability:
        return UnavailableCapability(
            capability_id=capability_id,
            reason_code=UnavailableReasonCode.NOT_REGISTERED,
            message=f"{capability_id} is not registered",
            repair_plan=RepairPlan(
                steps=(f"install or register {capability_id}", "run a real health probe"),
                risk=RiskLevel.MEDIUM,
            ),
        )

    @staticmethod
    def _unavailable(
        metadata: CapabilityMetadata,
        reason_code: UnavailableReasonCode,
        message: str,
    ) -> UnavailableCapability:
        return UnavailableCapability(
            capability_id=metadata.capability_id,
            reason_code=reason_code,
            message=message,
            repair_plan=RepairPlan(
                steps=(f"inspect {metadata.capability_id}", "repair and re-run a real health probe"),
                risk=metadata.risk,
            ),
        )

    def _require_entry(self, capability_id: str) -> _Entry:
        try:
            return self._entries[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {capability_id}") from exc


def _sort_key(metadata: CapabilityMetadata) -> tuple[int, int, str]:
    return (_TIER_ORDER[metadata.tier], -metadata.priority, metadata.capability_id)


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


__all__ = [
    "CapabilityKind",
    "CapabilityTier",
    "DEFAULT_PRECEDENCE",
    "HealthStatus",
    "RiskLevel",
    "Determinism",
    "UnavailableReasonCode",
    "CapabilitySource",
    "LicenseMetadata",
    "LatencyMetadata",
    "CostMetadata",
    "CapabilityMetadata",
    "RepairPlan",
    "UnavailableCapability",
    "CapabilityRequest",
    "SelectionResult",
    "CapabilityRegistry",
]
