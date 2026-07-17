from __future__ import annotations

import json

import pytest

from agent.self_model import (
    CapabilityState,
    CapabilityTransition,
    EvidenceClass,
    SelfModelSnapshot,
    SourceReceipt,
    _safe_mapping,
    build_snapshot,
)


def _receipt(name: str = "health-1") -> SourceReceipt:
    return SourceReceipt(name, EvidenceClass.MEASURED, "runtime_health")


def _capability(**changes) -> CapabilityState:
    values = {
        "capability_id": "filesystem.read",
        "modality": "filesystem",
        "installed": True,
        "configured": True,
        "healthy": True,
        "authorized": True,
        "verified": True,
        "authority_level": 2,
        "authority_ceiling": 3,
        "budget_remaining": 10,
        "verifier_ref": "verify:filesystem",
        "rollback_ref": "rollback:filesystem",
        "owner_scope": "profile:default",
        "source_receipts": (_receipt(),),
    }
    values.update(changes)
    return CapabilityState(**values)


def test_snapshot_is_canonical_and_reports_availability_dimensions() -> None:
    snapshot = build_snapshot(
        profile_id="profile:default",
        tenant_id="tenant:local",
        identity_ref="agent:local",
        capabilities=(_capability(),),
        budgets={"tokens": 100, "actions": 4},
        snapshot_receipt=_receipt("snapshot-1"),
        active_providers=("provider:local",),
    )

    assert snapshot.capabilities[0].available is True
    assert json.loads(snapshot.to_json())["schema"] == "simplicio.self-model/v1"
    assert snapshot.to_json() == snapshot.to_json()
    assert len(snapshot.digest()) == 64


def test_capability_loss_and_recovery_are_typed_and_scoped() -> None:
    snapshot = build_snapshot(
        profile_id="profile:default",
        tenant_id="tenant:local",
        identity_ref="agent:local",
        capabilities=(_capability(),),
        budgets={"actions": 4},
        snapshot_receipt=_receipt("snapshot-1"),
    )

    degraded, event = snapshot.transition(
        "filesystem.read", False, _receipt("loss"), "runtime unavailable"
    )
    assert event is CapabilityTransition.LOSS
    assert degraded.capabilities[0].healthy is False
    assert "filesystem" in degraded.degraded_modalities
    recovered, event = degraded.transition(
        "filesystem.read", True, _receipt("recovery"), "runtime restored"
    )
    assert event is CapabilityTransition.RECOVERY
    assert recovered.capabilities[0].healthy is True
    assert "filesystem" not in recovered.degraded_modalities


def test_authority_can_only_be_attenuated() -> None:
    capability = _capability().attenuate(1, _receipt("policy-1"))
    assert capability.authority_level == 1
    with pytest.raises(ValueError, match="attenuated"):
        capability.attenuate(2, _receipt("policy-2"))


@pytest.mark.parametrize(
    "changes",
    (
        {"healthy": False},
        {"authorized": False},
        {"verified": False},
        {"authority_level": 1},
        {"budget_remaining": 0},
    ),
)
def test_execution_contract_fails_closed_on_health_authority_and_budget(
    changes: dict[str, object],
) -> None:
    assert _capability().can_execute(required_authority=2) is True
    assert _capability(**changes).can_execute(required_authority=2) is False


def test_execution_contract_rejects_ambiguous_state_and_invalid_limits() -> None:
    with pytest.raises(TypeError, match="healthy must be a bool"):
        _capability(healthy="unknown")
    with pytest.raises(TypeError, match="authority_level must be an int"):
        _capability(authority_level=True)
    with pytest.raises(ValueError, match="required_authority must be non-negative"):
        _capability().can_execute(required_authority=-1)


def test_untrusted_sources_and_secret_like_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="untrusted"):
        SourceReceipt("receipt-1", "MEASURED", "tool_output")
    with pytest.raises(ValueError, match="secret-like"):
        SourceReceipt("api_token_receipt", "MEASURED", "runtime_health")
    with pytest.raises(ValueError, match="secret-like"):
        build_snapshot(
            profile_id="profile:default",
            tenant_id="tenant:local",
            identity_ref="agent:local",
            capabilities=(_capability(),),
            budgets={"actions": 1},
            snapshot_receipt=_receipt("snapshot-2"),
            active_providers=("provider:api-key",),
        )


def test_verified_and_authorized_states_require_proof_and_ownership() -> None:
    with pytest.raises(ValueError, match="verifier"):
        _capability(verifier_ref="")
    with pytest.raises(ValueError, match="owner scope"):
        _capability(owner_scope="", authorized=True)
    with pytest.raises(ValueError, match="source receipt"):
        _capability(source_receipts=())


def test_profile_and_tenant_are_part_of_the_snapshot_boundary() -> None:
    snapshot = build_snapshot(
        profile_id="profile:a",
        tenant_id="tenant:a",
        identity_ref="agent:a",
        capabilities=(_capability(),),
        budgets={"actions": 1},
        snapshot_receipt=_receipt("snapshot-a"),
    )
    other = SelfModelSnapshot(
        profile_id="profile:b",
        tenant_id="tenant:b",
        identity_ref="agent:b",
        capabilities=(_capability(),),
        budgets={"actions": 1},
        snapshot_receipt=_receipt("snapshot-b"),
    )
    assert snapshot.profile_id != other.profile_id
    assert snapshot.tenant_id != other.tenant_id


def test_clean_rejects_blank_values() -> None:
    with pytest.raises(ValueError, match="must be non-empty"):
        _capability(capability_id="   ")


def test_safe_mapping_normalizes_nested_maps_and_lists_and_sorts_keys() -> None:
    result = _safe_mapping(
        {"z": 1, "nested": {"b": [1, 2], "a": "x"}},
        "field",
    )
    assert list(result.keys()) == ["nested", "z"]
    assert result["nested"] == {"a": "x", "b": ["1", "2"]}


def test_authority_and_budget_reject_negative_values() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _capability(authority_level=-1)
    with pytest.raises(ValueError, match="non-negative"):
        _capability(authority_ceiling=-1)
    with pytest.raises(ValueError, match="exceed its policy ceiling"):
        _capability(authority_level=5, authority_ceiling=3)
    with pytest.raises(ValueError, match="budget_remaining must be non-negative"):
        _capability(budget_remaining=-1)


def test_optional_ref_fields_are_cleaned_when_present() -> None:
    capability = _capability(
        verified=False,
        verifier_ref="verify:extra ",
        rollback_ref=" rollback:extra",
        authorized=False,
        owner_scope=" profile:extra ",
    )
    assert capability.verifier_ref == "verify:extra"
    assert capability.rollback_ref == "rollback:extra"
    assert capability.owner_scope == "profile:extra"


def test_can_execute_rejects_non_int_required_authority() -> None:
    with pytest.raises(TypeError, match="required_authority must be an int"):
        _capability().can_execute(required_authority="2")


def test_with_health_requires_a_source_receipt() -> None:
    with pytest.raises(TypeError, match="SourceReceipt"):
        _capability().with_health(False, "not-a-receipt", "reason")


def test_attenuate_requires_a_source_receipt() -> None:
    with pytest.raises(TypeError, match="SourceReceipt"):
        _capability().attenuate(1, "not-a-receipt")


def test_snapshot_rejects_duplicate_capability_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        SelfModelSnapshot(
            profile_id="profile:a",
            tenant_id="tenant:a",
            identity_ref="agent:a",
            capabilities=(_capability(), _capability()),
            budgets={"actions": 1},
        )


def test_snapshot_rejects_invalid_budget_values() -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        SelfModelSnapshot(
            profile_id="profile:a",
            tenant_id="tenant:a",
            identity_ref="agent:a",
            capabilities=(_capability(),),
            budgets={"actions": -1},
        )
    with pytest.raises(ValueError, match="non-negative integer"):
        SelfModelSnapshot(
            profile_id="profile:a",
            tenant_id="tenant:a",
            identity_ref="agent:a",
            capabilities=(_capability(),),
            budgets={"actions": "many"},
        )


def test_snapshot_rejects_non_receipt_snapshot_receipt() -> None:
    with pytest.raises(TypeError, match="SourceReceipt"):
        SelfModelSnapshot(
            profile_id="profile:a",
            tenant_id="tenant:a",
            identity_ref="agent:a",
            capabilities=(_capability(),),
            budgets={"actions": 1},
            snapshot_receipt="not-a-receipt",
        )


def test_transition_rejects_unknown_capability_and_no_op_transitions() -> None:
    snapshot = build_snapshot(
        profile_id="profile:default",
        tenant_id="tenant:local",
        identity_ref="agent:local",
        capabilities=(_capability(),),
        budgets={"actions": 4},
        snapshot_receipt=_receipt("snapshot-1"),
    )
    with pytest.raises(KeyError):
        snapshot.transition("unknown.capability", False, _receipt("x"), "reason")
    with pytest.raises(ValueError, match="does not change state"):
        snapshot.transition("filesystem.read", True, _receipt("y"), "reason")


def test_build_snapshot_requires_a_source_receipt() -> None:
    with pytest.raises(TypeError, match="snapshot_receipt is required"):
        build_snapshot(
            profile_id="profile:default",
            tenant_id="tenant:local",
            identity_ref="agent:local",
            capabilities=(_capability(),),
            budgets={"actions": 1},
            snapshot_receipt="not-a-receipt",
        )
