"""Focused tests for the bounded issue #129 update contract."""

from __future__ import annotations

import json

from agent.update_rollback_contract import (
    ChecksumEvidence,
    IntegrationFlags,
    ModelVersionPin,
    ReadinessStatus,
    RollbackTarget,
    UpdateApproval,
    UpdateRollbackContract,
    audit_update_rollback,
)


UPDATE_SHA = "a" * 64
ROLLBACK_SHA = "b" * 64


def _valid_contract(**overrides: object) -> UpdateRollbackContract:
    values: dict[str, object] = {
        "model_version_pin": ModelVersionPin("local-model", "1.2.3"),
        "update_artifact": "agent-1.2.3.tar",
        "update_checksum": ChecksumEvidence(
            artifact="agent-1.2.3.tar", sha256=UPDATE_SHA, receipt="sha:update"
        ),
        "approval": UpdateApproval(
            approved=True,
            approved_by="operator",
            approval_id="approval-1",
            receipt="approval-receipt-1",
        ),
        "rollback_target": RollbackTarget(
            model_version_pin=ModelVersionPin("local-model", "1.2.2"),
            artifact="agent-1.2.2.tar",
            checksum=ChecksumEvidence(
                artifact="agent-1.2.2.tar", sha256=ROLLBACK_SHA, receipt="sha:rollback"
            ),
            proof_receipt="rollback-proof-1",
            proof_verified=True,
        ),
    }
    values.update(overrides)
    return UpdateRollbackContract(**values)


def test_integrations_are_default_off_and_demo_requires_explicit_flag() -> None:
    assert IntegrationFlags().default_off
    assert not audit_update_rollback(_valid_contract()).blockers

    audit = audit_update_rollback(
        _valid_contract(flags=IntegrationFlags(demo_mode=True))
    )
    assert audit.readiness is ReadinessStatus.BLOCKED
    assert any("demo mode" in blocker for blocker in audit.blockers)


def test_model_pin_rejects_version_ranges() -> None:
    audit = audit_update_rollback(
        _valid_contract(model_version_pin=ModelVersionPin("local-model", "^1.2"))
    )
    assert not audit.is_ready
    assert "model version pin: invalid exact pin" in audit.blockers


def test_approval_is_required() -> None:
    audit = audit_update_rollback(_valid_contract(approval=UpdateApproval()))
    assert not audit.is_ready
    assert "update approval: missing or invalid" in audit.blockers


def test_update_checksum_must_match_artifact_and_be_sha256() -> None:
    audit = audit_update_rollback(
        _valid_contract(
            update_checksum=ChecksumEvidence(
                artifact="other.tar", sha256="not-a-sha", receipt="receipt"
            )
        )
    )
    assert not audit.is_ready
    assert "update checksum: invalid SHA-256 evidence" in audit.blockers


def test_missing_rollback_proof_fails_closed() -> None:
    audit = audit_update_rollback(_valid_contract(rollback_target=None))
    assert audit.readiness is ReadinessStatus.BLOCKED
    assert not audit.is_ready
    assert any("rollback proof" in blocker for blocker in audit.blockers)


def test_unverified_rollback_target_fails_closed_even_with_checksum() -> None:
    target = _valid_contract().rollback_target
    assert target is not None
    audit = audit_update_rollback(
        _valid_contract(
            rollback_target=RollbackTarget(
                model_version_pin=target.model_version_pin,
                artifact=target.artifact,
                checksum=target.checksum,
                proof_receipt=target.proof_receipt,
                proof_verified=False,
            )
        )
    )
    assert not audit.is_ready
    assert any("rollback verification" in blocker for blocker in audit.blockers)


def test_complete_contract_is_ready_but_does_not_execute_an_updater() -> None:
    audit = audit_update_rollback(_valid_contract())
    assert audit.readiness is ReadinessStatus.READY
    assert audit.verified_checks[-1] == "rollback-proof"
    assert audit.receipt.status is ReadinessStatus.READY


def test_receipt_is_idempotent_for_equivalent_contracts() -> None:
    first = audit_update_rollback(_valid_contract())
    second = audit_update_rollback(_valid_contract())
    assert first.receipt.receipt_sha256 == second.receipt.receipt_sha256
    assert first.receipt.request_sha256 == second.receipt.request_sha256
    assert first.receipt.idempotency_key == second.receipt.idempotency_key


def test_receipt_changes_when_contract_evidence_changes() -> None:
    first = audit_update_rollback(_valid_contract())
    second = audit_update_rollback(
        _valid_contract(
            approval=UpdateApproval(
                approved=True,
                approved_by="operator",
                approval_id="approval-2",
                receipt="approval-receipt-2",
            )
        )
    )
    assert first.receipt.receipt_sha256 != second.receipt.receipt_sha256


def test_audit_receipt_is_json_safe_and_contract_has_no_side_effects() -> None:
    audit = audit_update_rollback(_valid_contract())
    encoded = json.dumps(audit.to_dict(), sort_keys=True)
    assert "updater" not in encoded.lower()
    assert audit.receipt.to_dict()["schema"].endswith("/v1")
