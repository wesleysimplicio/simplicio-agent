"""Deterministic capability registration and routing.

The capability registry is deliberately a small, side-effect-free policy
layer.  Providers (and transport integrations) own execution; this module
only describes what is available and chooses a candidate in an explicit
order.  In particular, it never silently reorders fallbacks by health, cost,
or an arbitrary score.  This makes route decisions reproducible and keeps a
conversation's selected capability stable for its lifetime.

The public dataclasses are JSON-friendly and use only the standard library so
the registry can be used by the CLI, the daemon, and tests without importing a
transport or model SDK.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any


class Health(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Determinism(StrEnum):
    DETERMINISTIC = "deterministic"
    REPEATABLE = "repeatable"
    NONDETERMINISTIC = "nondeterministic"
    UNKNOWN = "unknown"


class ReasonCode(StrEnum):
    SELECTED = "selected"
    NO_SUCH_CAPABILITY = "no_such_capability"
    NO_COMPATIBLE_CANDIDATE = "no_compatible_candidate"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    HEALTH_UNAVAILABLE = "health_unavailable"
    RISK_REQUIRES_CONSENT = "risk_requires_consent"
    NONDETERMINISTIC_REQUIRES_CONSENT = "nondeterministic_requires_consent"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
    PINNED_CAPABILITY = "pinned_capability"
    PINNED_CAPABILITY_UNAVAILABLE = "pinned_capability_unavailable"
    FALLBACK_EXHAUSTED = "fallback_exhausted"
    REPAIR_REQUIRES_CONSENT = "repair_requires_consent"
    REPAIR_APPLIED = "repair_applied"


class RepairAction(StrEnum):
    HEALTH_CHECK = "health_check"
    REINSTALL = "reinstall"
    REAUTHENTICATE = "reauthenticate"
    SWITCH_SOURCE = "switch_source"
    LOWER_RISK = "lower_risk"


_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:[-+][0-9A-Za-z.-]+)?$")
_HEALTH_ORDER = {Health.HEALTHY: 0, Health.DEGRADED: 1, Health.UNKNOWN: 2, Health.UNHEALTHY: 3}
_RISK_ORDER = {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2, Risk.CRITICAL: 3}


def _nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _tuple_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    result = tuple(_nonempty(value, field_name) for value in values)
    if not result:
        raise ValueError(f"{field_name} must contain at least one value")
    return result


@dataclasses.dataclass(frozen=True, slots=True)
class CapabilityMetadata:
    """The immutable facts used by routing policy."""

    version: str
    source: str
    license: str
    platforms: tuple[str, ...]
    health: Health = Health.HEALTHY
    risk: Risk = Risk.LOW
    determinism: Determinism = Determinism.DETERMINISTIC
    cost: float = 0.0
    health_detail: str = ""

    def __post_init__(self) -> None:
        version = _nonempty(self.version, "version")
        if not _VERSION.match(version):
            raise ValueError(f"version must be semver-like, got {version!r}")
        _nonempty(self.source, "source")
        _nonempty(self.license, "license")
        object.__setattr__(self, "platforms", _tuple_strings(self.platforms, "platforms"))
        if not isinstance(self.health, Health):
            object.__setattr__(self, "health", Health(self.health))
        if not isinstance(self.risk, Risk):
            object.__setattr__(self, "risk", Risk(self.risk))
        if not isinstance(self.determinism, Determinism):
            object.__setattr__(self, "determinism", Determinism(self.determinism))
        if isinstance(self.cost, bool) or not isinstance(self.cost, (int, float)) or self.cost < 0:
            raise ValueError("cost must be a non-negative number")
        object.__setattr__(self, "cost", float(self.cost))

    def supports_platform(self, platform: str | None) -> bool:
        return platform is None or platform in self.platforms or "*" in self.platforms

    @property
    def platform(self) -> str | tuple[str, ...]:
        """Compatibility view for callers with a singular platform field."""
        return self.platforms[0] if len(self.platforms) == 1 else self.platforms

    @property
    def cost_usd(self) -> float:
        """Compatibility name for the estimated per-use cost."""
        return self.cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source": self.source,
            "license": self.license,
            "platforms": list(self.platforms),
            "health": self.health.value,
            "risk": self.risk.value,
            "determinism": self.determinism.value,
            "cost": self.cost,
            "health_detail": self.health_detail,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class Capability:
    """One routable implementation of a capability."""

    name: str
    metadata: CapabilityMetadata
    fallback: tuple[str, ...] = ()
    repair_actions: tuple[RepairAction, ...] = ()
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _nonempty(self.name, "name").lower())
        if not isinstance(self.metadata, CapabilityMetadata):
            raise TypeError("metadata must be a CapabilityMetadata instance")
        object.__setattr__(self, "fallback", tuple(_nonempty(x, "fallback") for x in self.fallback))
        object.__setattr__(self, "repair_actions", tuple(RepairAction(x) for x in self.repair_actions))

    @property
    def id(self) -> str:
        """Stable spelling retained for callers that call the name an id."""
        return self.name

    @property
    def version(self) -> str:
        return self.metadata.version

    def to_dict(self) -> dict[str, Any]:
        result = {"name": self.name, **self.metadata.to_dict()}
        result["fallback"] = list(self.fallback)
        result["repair_actions"] = [x.value for x in self.repair_actions]
        result["enabled"] = self.enabled
        return result


# Friendly alias for integrations that use "spec" terminology.
CapabilitySpec = Capability


@dataclasses.dataclass(frozen=True, slots=True)
class RepairPlan:
    capability: str
    reason: ReasonCode
    actions: tuple[RepairAction, ...]
    requires_consent: bool = True
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability", _nonempty(self.capability, "capability").lower())
        object.__setattr__(self, "reason", ReasonCode(self.reason))
        object.__setattr__(self, "actions", tuple(RepairAction(x) for x in self.actions))
        if not self.actions:
            raise ValueError("a repair plan must contain at least one action")
        # Repair is an external/state-changing operation.  It must never be
        # represented as consent-free even when a caller passes False.
        object.__setattr__(self, "requires_consent", True)


@dataclasses.dataclass(frozen=True, slots=True)
class RouteDecision:
    capability: str | None
    reason: ReasonCode
    attempted: tuple[str, ...] = ()
    repair_plan: RepairPlan | None = None
    session_id: str | None = None
    pinned: bool = False

    @property
    def selected(self) -> bool:
        return self.capability is not None and self.reason in {
            ReasonCode.SELECTED, ReasonCode.PINNED_CAPABILITY
        }

    @property
    def reason_code(self) -> str:
        return self.reason.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "reason": self.reason.value,
            "attempted": list(self.attempted),
            "repair_plan": dataclasses.asdict(self.repair_plan) if self.repair_plan else None,
            "session_id": self.session_id,
            "pinned": self.pinned,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class SessionPin:
    session_id: str
    capability: str
    version: str


class CapabilityRegistry:
    """Registry and deterministic router for capability implementations.

    ``fallback`` on a capability is an ordered policy list.  It is followed
    exactly as declared, and no fallback is inferred from registration order.
    A route is pinned to a session after the first successful selection.
    ``consent=True`` only authorizes a repair plan; it does not bypass a risk
    or platform policy.
    """

    def __init__(self, capabilities: Iterable[Capability] = ()) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._pins: dict[str, SessionPin] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: Capability) -> None:
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability instance")
        if capability.name in self._capabilities:
            raise ValueError(f"capability already registered: {capability.name}")
        self._capabilities[capability.name] = capability

    register_capability = register

    def replace(self, capability: Capability) -> None:
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability instance")
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        if not isinstance(name, str):
            return None
        return self._capabilities.get(name.strip().lower())

    get_capability = get

    def list(self) -> tuple[Capability, ...]:
        return tuple(self._capabilities[name] for name in sorted(self._capabilities))

    capabilities = list

    def pin_session(self, session_id: str, capability: str) -> SessionPin:
        session_id = _nonempty(session_id, "session_id")
        selected = self.get(capability)
        if selected is None:
            raise KeyError(f"unknown capability: {capability}")
        pin = SessionPin(session_id, selected.name, selected.version)
        self._pins[session_id] = pin
        return pin

    def unpin_session(self, session_id: str) -> None:
        self._pins.pop(session_id, None)

    def session_pin(self, session_id: str) -> SessionPin | None:
        return self._pins.get(session_id)

    def _repair(self, capability: Capability, reason: ReasonCode) -> RepairPlan | None:
        if not capability.repair_actions:
            return None
        return RepairPlan(
            capability=capability.name,
            reason=reason,
            actions=capability.repair_actions,
            summary=capability.metadata.health_detail,
        )

    def _eligible(
        self,
        capability: Capability,
        *,
        platform: str | None,
        max_cost: float | None,
        allow_degraded: bool,
        allow_unknown_health: bool,
        allow_risky: bool,
        allow_nondeterministic: bool,
    ) -> tuple[bool, ReasonCode, RepairPlan | None]:
        meta = capability.metadata
        if not capability.enabled:
            return False, ReasonCode.HEALTH_UNAVAILABLE, self._repair(capability, ReasonCode.HEALTH_UNAVAILABLE)
        if not meta.supports_platform(platform):
            return False, ReasonCode.PLATFORM_UNSUPPORTED, None
        if max_cost is not None and meta.cost > max_cost:
            return False, ReasonCode.COST_LIMIT_EXCEEDED, None
        if meta.risk in (Risk.HIGH, Risk.CRITICAL) and not allow_risky:
            return False, ReasonCode.RISK_REQUIRES_CONSENT, self._repair(capability, ReasonCode.RISK_REQUIRES_CONSENT)
        if meta.determinism is Determinism.NONDETERMINISTIC and not allow_nondeterministic:
            return False, ReasonCode.NONDETERMINISTIC_REQUIRES_CONSENT, self._repair(capability, ReasonCode.NONDETERMINISTIC_REQUIRES_CONSENT)
        if meta.health is Health.UNHEALTHY:
            return False, ReasonCode.HEALTH_UNAVAILABLE, self._repair(capability, ReasonCode.HEALTH_UNAVAILABLE)
        if meta.health is Health.DEGRADED and not allow_degraded:
            return False, ReasonCode.HEALTH_UNAVAILABLE, self._repair(capability, ReasonCode.HEALTH_UNAVAILABLE)
        if meta.health is Health.UNKNOWN and not allow_unknown_health:
            return False, ReasonCode.HEALTH_UNAVAILABLE, self._repair(capability, ReasonCode.HEALTH_UNAVAILABLE)
        return True, ReasonCode.SELECTED, None

    def route(
        self,
        capability: str,
        *,
        session_id: str | None = None,
        session: str | None = None,
        platform: str | None = None,
        max_cost: float | None = None,
        allow_degraded: bool = False,
        allow_unknown_health: bool = False,
        allow_risky: bool = False,
        allow_nondeterministic: bool = False,
        consent: bool = False,
        pin: bool = True,
    ) -> RouteDecision:
        """Choose the first eligible candidate in the declared fallback order."""
        if session_id is not None and session is not None and session_id != session:
            raise ValueError("session and session_id disagree")
        session_id = session_id if session_id is not None else session
        if not isinstance(capability, str) or not capability.strip():
            return RouteDecision(None, ReasonCode.NO_SUCH_CAPABILITY, session_id=session_id)
        name = capability.strip().lower()

        if session_id is not None:
            session_id = _nonempty(session_id, "session_id")
            existing_pin = self._pins.get(session_id)
            if existing_pin is not None:
                pinned = self.get(existing_pin.capability)
                if pinned is None or pinned.version != existing_pin.version:
                    return RouteDecision(
                        None, ReasonCode.PINNED_CAPABILITY_UNAVAILABLE,
                        attempted=(existing_pin.capability,), session_id=session_id, pinned=True,
                    )
                ok, reason, repair = self._eligible(
                    pinned, platform=platform, max_cost=max_cost,
                    allow_degraded=allow_degraded, allow_unknown_health=allow_unknown_health,
                    allow_risky=allow_risky, allow_nondeterministic=allow_nondeterministic,
                )
                if ok:
                    return RouteDecision(pinned.name, ReasonCode.PINNED_CAPABILITY,
                                         (pinned.name,), session_id=session_id, pinned=True)
                return RouteDecision(None, ReasonCode.PINNED_CAPABILITY_UNAVAILABLE,
                                     (pinned.name,), repair, session_id=session_id, pinned=True)

        requested = self.get(name)
        if requested is None:
            return RouteDecision(None, ReasonCode.NO_SUCH_CAPABILITY, session_id=session_id)
        ordered: list[str] = []
        for candidate_name in (requested.name, *requested.fallback):
            candidate_name = candidate_name.strip().lower()
            if candidate_name not in ordered:
                ordered.append(candidate_name)

        attempted: list[str] = []
        last_reason = ReasonCode.FALLBACK_EXHAUSTED
        repair: RepairPlan | None = None
        for candidate_name in ordered:
            attempted.append(candidate_name)
            candidate = self.get(candidate_name)
            if candidate is None:
                last_reason = ReasonCode.NO_COMPATIBLE_CANDIDATE
                continue
            ok, reason, candidate_repair = self._eligible(
                candidate, platform=platform, max_cost=max_cost,
                allow_degraded=allow_degraded, allow_unknown_health=allow_unknown_health,
                allow_risky=allow_risky or consent, allow_nondeterministic=allow_nondeterministic or consent,
            )
            if ok:
                if session_id is not None and pin:
                    self.pin_session(session_id, candidate.name)
                return RouteDecision(candidate.name, ReasonCode.SELECTED, tuple(attempted),
                                     session_id=session_id, pinned=False)
            last_reason = reason
            repair = candidate_repair or repair

        if repair is not None and not consent:
            last_reason = ReasonCode.REPAIR_REQUIRES_CONSENT
        elif len(attempted) > 1 and last_reason is ReasonCode.NO_COMPATIBLE_CANDIDATE:
            last_reason = ReasonCode.FALLBACK_EXHAUSTED
        return RouteDecision(None, last_reason, tuple(attempted), repair, session_id=session_id)

    resolve = route

    def fallback_order(self, capability: str) -> tuple[str, ...]:
        selected = self.get(capability)
        if selected is None:
            return ()
        return tuple(dict.fromkeys((selected.name, *selected.fallback)))

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        """Return a stable, serialization-ready registry snapshot."""
        return tuple(capability.to_dict() for capability in self.list())


def metadata_from_dict(raw: Mapping[str, Any]) -> CapabilityMetadata:
    """Construct metadata from a fixture/config mapping."""
    return CapabilityMetadata(
        version=raw["version"], source=raw["source"], license=raw["license"],
        platforms=tuple(raw["platforms"]), health=raw.get("health", Health.HEALTHY),
        risk=raw.get("risk", Risk.LOW), determinism=raw.get("determinism", Determinism.DETERMINISTIC),
        cost=raw.get("cost", 0.0), health_detail=raw.get("health_detail", ""),
    )


def capability_from_dict(raw: Mapping[str, Any]) -> Capability:
    return Capability(
        name=raw["name"], metadata=metadata_from_dict(raw),
        fallback=tuple(raw.get("fallback", ())),
        repair_actions=tuple(raw.get("repair_actions", ())), enabled=raw.get("enabled", True),
    )


def registry_from_dicts(rows: Sequence[Mapping[str, Any]]) -> CapabilityRegistry:
    return CapabilityRegistry(capability_from_dict(row) for row in rows)


# Names used by earlier prototypes and by catalog adapters.  Keeping these as
# aliases costs no schema surface while allowing callers to describe the same
# policy object as either a registry or a router.
CapabilityRecord = Capability
CapabilityRouter = CapabilityRegistry
CapabilityHealth = Health
CapabilityRisk = Risk


__all__ = [
    "Capability", "CapabilityMetadata", "CapabilityRecord", "CapabilityRegistry",
    "CapabilityRouter", "CapabilitySpec", "CapabilityHealth", "CapabilityRisk",
    "Determinism", "Health", "ReasonCode", "RepairAction", "RepairPlan",
    "Risk", "RouteDecision", "SessionPin", "capability_from_dict",
    "metadata_from_dict", "registry_from_dicts",
]
