"""Focused tests for the bounded issue #127 runtime-bundle contract."""

from __future__ import annotations

import json

import pytest

from agent.runtime_bundle_contract import (
    ArtifactSurface,
    ArtifactSurfaceEvidence,
    ChecksumEvidence,
    HealthReadinessEvidence,
    HealthStatus,
    KernelIdentity,
    ReadinessStatus,
    RuntimeBundleContract,
    RuntimeVersionPin,
    SurfaceEvidenceStatus,
    VerificationStatus,
    sha256_bytes,
    verify_runtime_bundle,
)


SHA256 = "a" * 64


def _core() -> tuple[KernelIdentity, RuntimeVersionPin, ChecksumEvidence, HealthReadinessEvidence]:
    identity = KernelIdentity("simplicio", "3.5.0", "commit-127", "1")
    pin = RuntimeVersionPin("simplicio", "3.5.0", "commit-127", "1")
    checksum = ChecksumEvidence(SHA256, SHA256, "sha256-receipt")
    health = HealthReadinessEvidence(
        HealthStatus.HEALTHY,
        ReadinessStatus.READY,
        "1",
        capabilities=("handshake", "verify"),
        receipt="health-receipt",
    )
    return identity, pin, checksum, health


def _surface(surface: ArtifactSurface, *, digest: str = SHA256) -> ArtifactSurfaceEvidence:
    return ArtifactSurfaceEvidence(
        surface,
        "3.5.0",
        digest,
        receipt=f"receipt-{surface.value}",
        status=SurfaceEvidenceStatus.VERIFIED,
    )


def test_empty_contract_fails_closed_and_does_not_claim_artifact_verification():
    receipt = RuntimeBundleContract().verify()

    assert receipt.status is VerificationStatus.BLOCKED
    assert receipt.is_verified is False
    assert receipt.all_artifacts_verified is False
    assert "kernel identity is missing" in receipt.blockers
    assert "no claim that every official artifact is verified" in receipt.scope


def test_one_explicit_surface_is_verified_without_claiming_the_full_matrix():
    identity, pin, checksum, health = _core()
    receipt = RuntimeBundleContract(
        kernel_identity=identity,
        version_pin=pin,
        checksum=checksum,
        health=health,
        artifact_surfaces=(_surface(ArtifactSurface.CLI),),
    ).verify()

    assert receipt.status is VerificationStatus.PARTIAL
    assert receipt.verified_surfaces == (ArtifactSurface.CLI,)
    assert set(receipt.unverified_surfaces) == set(ArtifactSurface) - {ArtifactSurface.CLI}
    assert receipt.all_artifacts_verified is False
    assert all(
        blocker.startswith("artifact surface unverified:")
        for blocker in receipt.blockers
    )


def test_bounded_contract_can_verify_only_a_declared_subset():
    identity, pin, checksum, health = _core()
    receipt = verify_runtime_bundle(
        kernel_identity=identity,
        version_pin=pin,
        checksum=checksum,
        health=health,
        artifact_surfaces=(_surface(ArtifactSurface.BUNDLE),),
        required_surfaces=(ArtifactSurface.BUNDLE,),
    )

    assert receipt.status is VerificationStatus.VERIFIED
    assert receipt.verified_surfaces == (ArtifactSurface.BUNDLE,)
    assert receipt.unverified_surfaces == ()
    assert receipt.all_artifacts_verified is False


def test_kernel_version_protocol_and_checksum_drift_block_readiness():
    identity, pin, checksum, health = _core()
    drifted_identity = KernelIdentity("simplicio", "3.5.1", "commit-127", "1")
    drifted_checksum = ChecksumEvidence(SHA256, "b" * 64, "sha256-receipt")
    receipt = RuntimeBundleContract(
        kernel_identity=drifted_identity,
        version_pin=pin,
        checksum=drifted_checksum,
        health=health,
        artifact_surfaces=(_surface(ArtifactSurface.CLI),),
        required_surfaces=(ArtifactSurface.CLI,),
    ).verify()

    assert receipt.status is VerificationStatus.BLOCKED
    assert receipt.kernel_verified is False
    assert receipt.checksum_verified is False
    assert any("kernel drift: version" in blocker for blocker in receipt.blockers)
    assert any("checksum drift" in blocker for blocker in receipt.blockers)


def test_unhealthy_or_wrong_protocol_handshake_blocks_readiness():
    identity, pin, checksum, _ = _core()
    health = HealthReadinessEvidence(
        HealthStatus.DEGRADED,
        ReadinessStatus.READY,
        "2",
        receipt="health-receipt",
    )
    receipt = RuntimeBundleContract(
        kernel_identity=identity,
        version_pin=pin,
        checksum=checksum,
        health=health,
        artifact_surfaces=(_surface(ArtifactSurface.CLI),),
        required_surfaces=(ArtifactSurface.CLI,),
    ).verify()

    assert receipt.status is VerificationStatus.BLOCKED
    assert receipt.health_verified is False
    assert any("health drift" in blocker for blocker in receipt.blockers)


def test_bad_checksum_shape_and_surface_drift_are_rejected():
    with pytest.raises(ValueError, match="64-character"):
        ChecksumEvidence("not-a-digest", SHA256, "receipt")

    identity, pin, checksum, health = _core()
    receipt = RuntimeBundleContract(
        kernel_identity=identity,
        version_pin=pin,
        checksum=checksum,
        health=health,
        artifact_surfaces=(_surface(ArtifactSurface.DESKTOP, digest="b" * 64),),
        required_surfaces=(ArtifactSurface.DESKTOP,),
    ).verify()

    assert receipt.status is VerificationStatus.BLOCKED
    assert receipt.drifted_surfaces == (ArtifactSurface.DESKTOP,)


def test_receipt_json_is_deterministic_and_bounded():
    identity, pin, checksum, health = _core()
    contract = RuntimeBundleContract(
        kernel_identity=identity,
        version_pin=pin,
        checksum=checksum,
        health=health,
        artifact_surfaces=(_surface(ArtifactSurface.CLI),),
    )
    first = contract.verify().to_json()
    second = contract.verify().to_json()
    payload = json.loads(first)

    assert first == second
    assert payload["schema"] == "simplicio.runtime-bundle/v1"
    assert payload["all_artifacts_verified"] is False
    assert payload["scope"].startswith("bounded metadata verification")
    assert "artifact bytes" not in first.lower()


def test_bounds_and_duplicate_surface_evidence_fail_closed():
    too_many = tuple(_surface(ArtifactSurface.CLI) for _ in range(7))
    with pytest.raises(ValueError, match="more than 6"):
        RuntimeBundleContract(artifact_surfaces=too_many)

    identity, pin, checksum, health = _core()
    receipt = RuntimeBundleContract(
        kernel_identity=identity,
        version_pin=pin,
        checksum=checksum,
        health=health,
        artifact_surfaces=(_surface(ArtifactSurface.CLI), _surface(ArtifactSurface.CLI)),
        required_surfaces=(ArtifactSurface.CLI,),
    ).verify()

    assert receipt.status is VerificationStatus.BLOCKED
    assert any("duplicate evidence" in blocker for blocker in receipt.blockers)
    assert sha256_bytes(b"runtime") == sha256_bytes(b"runtime")
