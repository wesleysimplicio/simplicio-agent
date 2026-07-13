from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.capability_registry import (
    Capability,
    CapabilityMetadata,
    CapabilityRegistry,
    Determinism,
    Health,
    ReasonCode,
    RepairAction,
    Risk,
    capability_from_dict,
    registry_from_dicts,
)


def capability(name: str, **kwargs) -> Capability:
    values = {
        "version": "1.0.0",
        "source": "test",
        "license": "MIT",
        "platforms": ("*",),
    }
    values.update(kwargs)
    metadata_keys = {
        "version",
        "source",
        "license",
        "platforms",
        "health",
        "risk",
        "determinism",
        "cost",
        "health_detail",
    }
    metadata = CapabilityMetadata(**{
        key: values.pop(key) for key in tuple(values) if key in metadata_keys
    })
    return Capability(name, metadata, **values)


def test_metadata_contains_all_routing_dimensions() -> None:
    item = capability(
        "local",
        health=Health.DEGRADED,
        risk=Risk.MEDIUM,
        determinism=Determinism.REPEATABLE,
        cost=0.25,
    )
    assert item.to_dict() == {
        "name": "local",
        "version": "1.0.0",
        "source": "test",
        "license": "MIT",
        "platforms": ["*"],
        "health": "degraded",
        "risk": "medium",
        "determinism": "repeatable",
        "cost": 0.25,
        "health_detail": "",
        "fallback": [],
        "repair_actions": [],
        "enabled": True,
    }


def test_metadata_validates_version_and_cost() -> None:
    with pytest.raises(ValueError, match="semver-like"):
        capability("bad", version="latest")
    with pytest.raises(ValueError, match="non-negative"):
        capability("bad", cost=-1)


def test_fallback_order_is_explicit_and_not_registration_order() -> None:
    registry = CapabilityRegistry([
        capability("last"),
        capability("requested", health=Health.UNHEALTHY, fallback=("second", "last")),
        capability("second"),
    ])
    result = registry.route("requested")
    assert result.capability == "second"
    assert result.attempted == ("requested", "second")
    assert registry.fallback_order("requested") == ("requested", "second", "last")


def test_missing_fallback_is_reported_deterministically() -> None:
    registry = CapabilityRegistry([
        capability("requested", health=Health.UNHEALTHY, fallback=("missing",))
    ])
    result = registry.route("requested")
    assert result.capability is None
    assert result.reason is ReasonCode.FALLBACK_EXHAUSTED
    assert result.attempted == ("requested", "missing")


def test_platform_and_cost_filters() -> None:
    registry = CapabilityRegistry([
        capability("linux", platforms=("linux",), cost=2),
        capability("cheap", platforms=("linux",), cost=1),
    ])
    assert (
        registry.route("linux", platform="win32").reason
        is ReasonCode.PLATFORM_UNSUPPORTED
    )
    assert (
        registry.route("linux", platform="linux", max_cost=1).reason
        is ReasonCode.COST_LIMIT_EXCEEDED
    )


def test_risk_and_nondeterminism_need_consent() -> None:
    registry = CapabilityRegistry([
        capability("danger", risk=Risk.HIGH),
        capability("random", determinism=Determinism.NONDETERMINISTIC),
    ])
    assert registry.route("danger").reason is ReasonCode.RISK_REQUIRES_CONSENT
    assert registry.route("danger", consent=True).capability == "danger"
    assert (
        registry.route("random").reason is ReasonCode.NONDETERMINISTIC_REQUIRES_CONSENT
    )
    assert registry.route("random", consent=True).capability == "random"


def test_unhealthy_candidate_returns_consent_required_repair_plan() -> None:
    item = capability(
        "offline",
        health=Health.UNHEALTHY,
        health_detail="missing binary",
        repair_actions=(RepairAction.REINSTALL,),
    )
    result = CapabilityRegistry([item]).route("offline")
    assert result.reason is ReasonCode.REPAIR_REQUIRES_CONSENT
    assert result.repair_plan is not None
    assert result.repair_plan.requires_consent is True
    assert result.repair_plan.actions == (RepairAction.REINSTALL,)


def test_session_pin_prevents_silent_switching() -> None:
    registry = CapabilityRegistry([
        capability("first", fallback=("second",)),
        capability("second"),
    ])
    assert registry.route("first", session_id="s1").capability == "first"
    registry.replace(capability("first", health=Health.UNHEALTHY, fallback=("second",)))
    pinned = registry.route("first", session_id="s1")
    assert pinned.capability is None
    assert pinned.reason is ReasonCode.PINNED_CAPABILITY_UNAVAILABLE
    assert pinned.pinned is True
    assert registry.session_pin("s1").version == "1.0.0"


def test_session_pin_is_stable_across_requested_alias() -> None:
    registry = CapabilityRegistry([
        capability("first", fallback=("second",)),
        capability("second"),
    ])
    registry.route("first", session_id="s1")
    assert (
        registry.route("second", session_id="s1").reason is ReasonCode.PINNED_CAPABILITY
    )


def test_fixture_round_trip() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "capabilities" / "router.json"
    rows = json.loads(fixture.read_text(encoding="utf-8"))
    registry = registry_from_dicts(rows)
    assert [item.name for item in registry.list()] == ["local", "remote"]
    assert registry.route("local", platform="win32").capability == "local"
    assert capability_from_dict(rows[0]).metadata.source == "bundled"


def test_duplicate_and_unknown_capability_are_rejected_or_reported() -> None:
    item = capability("same")
    registry = CapabilityRegistry([item])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(item)
    assert registry.route("unknown").reason is ReasonCode.NO_SUCH_CAPABILITY
