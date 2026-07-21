from __future__ import annotations

import pytest

from agent.capability_registry import Capability, CapabilityMetadata, CapabilityRegistry, Health
from agent.self_model import EvidenceClass, SourceReceipt
from agent.self_model_projection import project_registry


def _receipt(name: str, source: str) -> SourceReceipt:
    return SourceReceipt(name, EvidenceClass.MEASURED, source)


def _registry(*, health: Health = Health.HEALTHY, enabled: bool = True) -> CapabilityRegistry:
    return CapabilityRegistry(
        (
            Capability(
                "runtime.write",
                CapabilityMetadata(
                    version="1.0.0",
                    source="simplicio-runtime",
                    license="internal",
                    platforms=("*",),
                    health=health,
                ),
                enabled=enabled,
            ),
        )
    )


def _project(registry: CapabilityRegistry, **changes):
    values = {
        "registry": registry,
        "runtime_health": {"schema": "simplicio-runtime/health/v1", "healthy": True},
        "profile_id": "profile:default",
        "tenant_id": "tenant:local",
        "identity_ref": "agent:local",
        "configured": {"runtime.write": True},
        "authorized": {"runtime.write": True},
        "verified": {"runtime.write": True},
        "authority_levels": {"runtime.write": 2},
        "authority_ceilings": {"runtime.write": 3},
        "budget_remaining": {"runtime.write": 4},
        "budgets": {"actions": 4},
        "verifier_refs": {"runtime.write": "verify:runtime.write"},
        "rollback_refs": {"runtime.write": "rollback:runtime.write"},
        "owner_scopes": {"runtime.write": "profile:default/session:1"},
        "runtime_receipt": _receipt("runtime-1", "runtime_health"),
        "policy_receipt": _receipt("policy-1", "policy"),
        "snapshot_receipt": _receipt("snapshot-1", "self_model_projection"),
    }
    values.update(changes)
    return project_registry(**values)


def test_projection_derives_capability_health_and_policy_without_llm_claims() -> None:
    snapshot = _project(_registry())
    capability = snapshot.capabilities[0]

    assert capability.installed is True
    assert capability.configured is True
    assert capability.healthy is True
    assert capability.authorized is True
    assert capability.verified is True
    assert capability.available is True
    assert capability.can_execute(2) is True
    assert {receipt.source for receipt in capability.source_receipts} == {
        "runtime_health",
        "policy",
    }


def test_runtime_loss_is_visible_and_fails_closed() -> None:
    snapshot = _project(
        _registry(),
        runtime_health={"schema": "simplicio-runtime/health/v1", "healthy": False},
    )
    capability = snapshot.capabilities[0]

    assert capability.healthy is False
    assert capability.available is False
    assert capability.can_execute(0) is False
    assert "simplicio-runtime" in snapshot.degraded_modalities


def test_partial_permission_and_budget_exhaustion_remain_independent_dimensions() -> None:
    snapshot = _project(
        _registry(),
        authorized={"runtime.write": False},
        verified={"runtime.write": False},
        budget_remaining={"runtime.write": 0},
    )
    capability = snapshot.capabilities[0]

    assert capability.installed is True
    assert capability.configured is True
    assert capability.healthy is True
    assert capability.authorized is False
    assert capability.verified is False
    assert capability.budget_remaining == 0
    assert capability.can_execute(0) is False


def test_subagent_or_provider_authority_can_only_be_attenuated() -> None:
    snapshot = _project(_registry(), authority_attenuations={"runtime.write": 1})
    assert snapshot.capabilities[0].authority_level == 1

    with pytest.raises(ValueError, match="attenuated"):
        _project(_registry(), authority_attenuations={"runtime.write": 3})


def test_registry_health_is_not_promoted_by_runtime_health() -> None:
    snapshot = _project(_registry(health=Health.DEGRADED))
    capability = snapshot.capabilities[0]

    assert capability.healthy is False
    assert capability.available is False
    assert "registry health is degraded" in capability.limitations


def test_missing_or_spoofable_runtime_health_fails_closed() -> None:
    with pytest.raises(ValueError, match="measured boolean"):
        _project(_registry(), runtime_health={"status": "healthy"})

    with pytest.raises(ValueError, match="untrusted"):
        _project(_registry(), runtime_receipt=_receipt("tool-1", "tool_output"))
