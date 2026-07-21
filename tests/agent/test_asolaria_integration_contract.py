"""Unit and public-facade tests for issue #17's bounded contract slice."""

from __future__ import annotations

import json

import pytest

from agent.asolaria_integration_contract import (
    AsolariaIntegrationError,
    AsolariaIntegrationManifest,
    AsolariaProvenance,
    ClaimKind,
    CorrectiveGateReceipt,
    EvidenceStatus,
    GenerativeIdentity,
    IntegrationClaim,
    NestAddress,
    UnverifiablePhysicsClaim,
)


def _provenance(
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED,
) -> AsolariaProvenance:
    return AsolariaProvenance(
        source="public-specification",
        repository="JesseBrown1980/N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED",
        url="https://github.com/JesseBrown1980/N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED",
        revision="0123456789abcdef0123456789abcdef01234567",
        evidence=("source specification reviewed",),
        status=status,
        runtime_receipt="runtime://receipt/issue-17"
        if status is EvidenceStatus.VERIFIED
        else None,
    )


def test_address_is_canonical_and_supports_parent_child_navigation() -> None:
    address = NestAddress.parse("R.0.1")

    assert address.path == "R.0.1"
    assert address.depth == 2
    assert address.parent == NestAddress.parse("R.0")
    assert address.child(2) == NestAddress.parse("R.0.1.2")

    with pytest.raises(AsolariaIntegrationError):
        NestAddress.parse("R.01")


def test_identity_is_deterministic_and_exactly_eight_bytes_without_storage_claims() -> (
    None
):
    address = NestAddress.parse("R.0.1")
    first = GenerativeIdentity("issue-17", address)
    second = GenerativeIdentity("issue-17", address)
    other = GenerativeIdentity("issue-17", address.child(0))

    assert first.seed_bytes == second.seed_bytes
    assert len(first.seed_bytes) == 8
    assert first.seed_hex == first.seed_bytes.hex()
    assert first.digest != other.digest
    assert "physics" not in first.to_dict()


def test_corrective_gate_is_fail_closed_and_preserves_provenance_status() -> None:
    address = NestAddress.parse("R.0")
    verified = CorrectiveGateReceipt.evaluate(
        address,
        {"result": "ok"},
        {"result": "ok"},
        _provenance(EvidenceStatus.VERIFIED),
    )
    unverified = CorrectiveGateReceipt.evaluate(
        address, {"result": "ok"}, {"result": "ok"}, _provenance()
    )
    blocked = CorrectiveGateReceipt.evaluate(
        address,
        {"result": "ok"},
        {"result": "tampered"},
        _provenance(EvidenceStatus.VERIFIED),
    )

    assert verified.status is EvidenceStatus.VERIFIED
    assert verified.accepted is True
    assert unverified.status is EvidenceStatus.UNVERIFIED
    assert unverified.accepted is False
    assert blocked.status is EvidenceStatus.BLOCKED
    assert blocked.accepted is False
    assert blocked.provenance.status is EvidenceStatus.VERIFIED


def test_direct_receipt_construction_validates_hashes_and_status() -> None:
    with pytest.raises(AsolariaIntegrationError, match="SHA-256"):
        CorrectiveGateReceipt(
            address=NestAddress.parse("R"),
            reported_digest="bad",
            recomputed_digest="bad",
            provenance=_provenance(),
            status=EvidenceStatus.UNVERIFIED,
        )


def test_unverified_physics_claim_is_rejected_instead_of_inferred() -> None:
    with pytest.raises(UnverifiablePhysicsClaim):
        IntegrationClaim(
            statement="the gate preserves physical entropy",
            kind=ClaimKind.PHYSICS,
            falsifier="a measured counterexample",
            evidence=("text-only assertion",),
            status=EvidenceStatus.UNVERIFIED,
        )


def test_manifest_binds_hrm_and_n_nest_and_reports_runtime_gap_explicitly() -> None:
    address = NestAddress.parse("R.0.1")
    manifest = AsolariaIntegrationManifest(
        address=address,
        identity=GenerativeIdentity("issue-17", address),
        provenance=_provenance(),
        claims=(
            IntegrationClaim(
                statement="the corrective gate compares reported and recomputed digests",
                kind=ClaimKind.BEHAVIORAL,
                falsifier="different digests are accepted",
                evidence=("focused contract test",),
                status=EvidenceStatus.VERIFIED,
            ),
        ),
    )

    payload = json.loads(manifest.to_json())

    assert manifest.status is EvidenceStatus.UNVERIFIED
    assert payload["hrm_schema"] == "hrm-controller/v1"
    assert payload["nest_schema"] == "n-nest/v1"
    assert payload["status"] == "UNVERIFIED"
    assert "no runtime execution" in payload["boundary"]


def test_public_facade_exposes_the_contract_types() -> None:
    from simplicio_agent import asolaria

    assert asolaria.NestAddress.parse("R.0").path == "R.0"
    assert asolaria.CorrectiveGateReceipt is CorrectiveGateReceipt
