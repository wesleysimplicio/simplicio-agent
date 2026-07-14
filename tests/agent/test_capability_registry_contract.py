"""Focused contract tests for the additive capability registry."""

from __future__ import annotations

import pytest

from agent.capability_registry_contract import (
    DEFAULT_PRECEDENCE,
    CapabilityKind,
    CapabilityMetadata,
    CapabilityRegistry,
    CapabilityRequest,
    CapabilitySource,
    CapabilityTier,
    CostMetadata,
    Determinism,
    HealthStatus,
    LatencyMetadata,
    LicenseMetadata,
    RiskLevel,
    UnavailableReasonCode,
)


def _capability(
    capability_id: str,
    tier: CapabilityTier,
    *,
    kind: CapabilityKind = CapabilityKind.TOOL,
    health: HealthStatus = HealthStatus.READY,
    priority: int = 0,
    risk: RiskLevel = RiskLevel.LOW,
    determinism: Determinism = Determinism.DETERMINISTIC,
    platforms: frozenset[str] = frozenset({"any"}),
    license: LicenseMetadata | None = None,
) -> CapabilityMetadata:
    return CapabilityMetadata(
        capability_id=capability_id,
        kind=kind,
        tier=tier,
        version="1.2.3",
        source=CapabilitySource("https://example.invalid/repo", "abc123", "v1"),
        platforms=platforms,
        license=license or LicenseMetadata("MIT"),
        health=health,
        risk=risk,
        determinism=determinism,
        latency=LatencyMetadata(10, 25),
        cost=CostMetadata(0.01),
        schemas={"input": {"type": "object"}},
        permissions=frozenset({"read"}),
        priority=priority,
    )


def test_metadata_is_typed_and_keeps_code_and_asset_licenses_separate():
    metadata = _capability(
        "local-model",
        CapabilityTier.LOCAL_MODEL,
        kind=CapabilityKind.PROVIDER,
        license=LicenseMetadata("Apache-2.0", "Llama-3.1"),
    )

    assert metadata.kind is CapabilityKind.PROVIDER
    assert metadata.version == "1.2.3"
    assert metadata.source.commit == "abc123"
    assert metadata.platforms == frozenset({"any"})
    assert metadata.license.code == "Apache-2.0"
    assert metadata.license.weights_assets == "Llama-3.1"
    assert metadata.schemas["input"] == {"type": "object"}
    with pytest.raises(TypeError):
        metadata.schemas["new"] = {}  # type: ignore[index]


def test_default_precedence_is_explicit_and_registration_order_independent():
    registry = CapabilityRegistry()
    registry.register(_capability("remote", CapabilityTier.REMOTE_MODEL))
    registry.register(_capability("structured", CapabilityTier.STRUCTURED_API_FILE_CLI))
    registry.register(_capability("runtime", CapabilityTier.DETERMINISTIC_RUNTIME))
    registry.register(_capability("visual", CapabilityTier.VISUAL_COMPUTER_USE))

    assert DEFAULT_PRECEDENCE == (
        CapabilityTier.STRUCTURED_API_FILE_CLI,
        CapabilityTier.DETERMINISTIC_RUNTIME,
        CapabilityTier.SKILL_PLUGIN_MCP,
        CapabilityTier.LOCAL_MODEL,
        CapabilityTier.REMOTE_MODEL,
        CapabilityTier.VISUAL_COMPUTER_USE,
    )
    assert [item.capability_id for item in registry.list()] == [
        "structured",
        "runtime",
        "remote",
        "visual",
    ]
    result = registry.select()
    assert result.selected is not None
    assert result.selected.capability_id == "structured"
    assert [item.capability_id for item in result.fallbacks] == [
        "runtime",
        "remote",
        "visual",
    ]


def test_constraints_return_reason_code_and_consent_gated_repair_plan():
    registry = CapabilityRegistry()
    registry.register(
        _capability(
            "licensed-linux-tool",
            CapabilityTier.STRUCTURED_API_FILE_CLI,
            platforms=frozenset({"linux"}),
            license=LicenseMetadata("GPL-3.0", "Weights-Proprietary"),
            risk=RiskLevel.HIGH,
        )
    )

    result = registry.select(
        CapabilityRequest(
            platform="win32",
            accepted_licenses=frozenset({"MIT"}),
            max_risk=RiskLevel.MEDIUM,
        )
    )
    assert result.selected is None
    # Platform is checked first, so the receipt is deterministic.
    assert result.reason_code is UnavailableReasonCode.PLATFORM_UNSUPPORTED
    receipt = result.unavailable[0]
    assert receipt.repair_plan.requires_consent is True
    assert not receipt.repair_plan.is_authorized(consent=False, max_risk=RiskLevel.HIGH)
    assert receipt.repair_plan.is_authorized(consent=True, max_risk=RiskLevel.HIGH)

    missing = registry.select(CapabilityRequest(capability_id="missing"))
    assert missing.reason_code is UnavailableReasonCode.NOT_REGISTERED
    assert missing.unavailable[0].repair_plan.requires_consent is True


def test_health_probe_falls_back_without_automatic_repair_or_duplicate_attempts():
    registry = CapabilityRegistry()
    probe_calls = []
    registry.register(
        _capability("broken", CapabilityTier.STRUCTURED_API_FILE_CLI),
        health_probe=lambda: probe_calls.append("broken") or False,
    )
    registry.register(_capability("safe", CapabilityTier.DETERMINISTIC_RUNTIME))

    result = registry.select()
    assert result.selected is not None
    assert result.selected.capability_id == "safe"
    assert probe_calls == ["broken"]
    assert result.unavailable[0].reason_code is UnavailableReasonCode.HEALTH_CHECK_FAILED
    assert result.unavailable[0].repair_plan.requires_consent is True


def test_circuit_breaker_skips_failed_primary_then_allows_one_half_open_probe():
    registry = CapabilityRegistry(failure_threshold=2, cooldown_seconds=10)
    registry.register(_capability("primary", CapabilityTier.STRUCTURED_API_FILE_CLI))
    registry.register(_capability("fallback", CapabilityTier.REMOTE_MODEL))

    assert registry.select().selected.capability_id == "primary"  # type: ignore[union-attr]
    registry.record_failure("primary", now=100)
    assert registry.select().selected.capability_id == "primary"  # type: ignore[union-attr]
    registry.record_failure("primary", now=101)

    result = registry.select(now=105)
    assert result.selected is not None
    assert result.selected.capability_id == "fallback"
    assert any(
        item.reason_code is UnavailableReasonCode.CIRCUIT_OPEN
        for item in result.unavailable
    )

    half_open = registry.select(now=112)
    assert half_open.selected is not None
    assert half_open.selected.capability_id == "primary"
    blocked_second_probe = registry.select(now=113)
    assert blocked_second_probe.selected is not None
    assert blocked_second_probe.selected.capability_id == "fallback"
    registry.record_success("primary")
    assert registry.select(now=114).selected.capability_id == "primary"  # type: ignore[union-attr]


def test_risk_and_determinism_constraints_are_respected_before_selection():
    registry = CapabilityRegistry()
    registry.register(
        _capability(
            "remote-stochastic",
            CapabilityTier.REMOTE_MODEL,
            risk=RiskLevel.HIGH,
            determinism=Determinism.NON_DETERMINISTIC,
        )
    )

    result = registry.select(
        CapabilityRequest(max_risk=RiskLevel.MEDIUM, require_deterministic=True)
    )
    assert result.selected is None
    assert result.reason_code is UnavailableReasonCode.RISK_NOT_ACCEPTED
    assert result.unavailable[0].reason_code is UnavailableReasonCode.RISK_NOT_ACCEPTED
