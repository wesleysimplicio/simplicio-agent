"""Focused tests for the bounded issue #144 release handoff contract."""

from agent.release_handoff_contract import (
    DEFAULT_OFF_INTEGRATIONS,
    DEFAULT_RUNTIME_SURFACES,
    ArtifactEvidence,
    ChecksumEvidence,
    DefaultOffIntegrationEvidence,
    EvidenceStatus,
    LifecycleEvidence,
    ReadinessStatus,
    ReleaseHandoffContract,
    RuntimeSurfaceEvidence,
    audit_release_handoff,
)


SHA256 = "a" * 64


def _complete_contract() -> ReleaseHandoffContract:
    return ReleaseHandoffContract(
        artifacts=(ArtifactEvidence("dist/simplicio-agent.whl", "artifact-receipt"),),
        checksums=(
            ChecksumEvidence(
                "dist/simplicio-agent.whl", SHA256, "checksum-receipt"
            ),
        ),
        install=LifecycleEvidence("install-receipt", EvidenceStatus.VERIFIED),
        update=LifecycleEvidence("update-receipt", EvidenceStatus.VERIFIED),
        rollback=LifecycleEvidence("rollback-receipt", EvidenceStatus.VERIFIED),
        uninstall=LifecycleEvidence("uninstall-receipt", EvidenceStatus.VERIFIED),
        runtime_surfaces=tuple(
            RuntimeSurfaceEvidence(name, f"runtime-{name}", EvidenceStatus.VERIFIED)
            for name in DEFAULT_RUNTIME_SURFACES
        ),
        default_off_integrations=tuple(
            DefaultOffIntegrationEvidence(
                name, enabled=False, receipt=f"default-off-{name}", status=EvidenceStatus.VERIFIED
            )
            for name in DEFAULT_OFF_INTEGRATIONS
        ),
    )


def test_empty_contract_is_explicitly_blocked_and_does_not_claim_release_proof():
    audit = ReleaseHandoffContract().audit()

    assert audit.readiness is ReadinessStatus.BLOCKED
    assert audit.is_blocked is True
    assert audit.is_ready is False
    assert audit.evidence_complete is False
    assert audit.clean_machine_release_proof == "not_proven"
    assert any("readiness blocked" in blocker for blocker in audit.blockers)
    assert any("clean-machine release proof" in blocker for blocker in audit.blockers)


def test_complete_evidence_is_recorded_but_bounded_readiness_stays_blocked():
    audit = _complete_contract().audit()

    assert audit.evidence_complete is True
    assert audit.readiness is ReadinessStatus.BLOCKED
    assert audit.is_ready is False
    assert audit.blockers == (
        "readiness blocked: clean-machine release proof is outside the bounded issue #144 audit contract",
    )
    assert {
        "artifact:dist/simplicio-agent.whl",
        "checksum:dist/simplicio-agent.whl",
        "install",
        "update",
        "rollback",
        "uninstall",
        *(f"runtime:{name}" for name in DEFAULT_RUNTIME_SURFACES),
        *(f"default-off:{name}" for name in DEFAULT_OFF_INTEGRATIONS),
    } == set(audit.verified_checks)


def test_missing_checksum_and_lifecycle_receipts_are_blockers():
    audit = ReleaseHandoffContract(
        artifacts=(ArtifactEvidence("app.exe", "artifact-receipt"),),
        checksums=(),
    ).audit()

    assert "checksums: no SHA-256 evidence supplied" in audit.blockers
    assert "install: verified receipt is missing" in audit.blockers
    assert "update: verified receipt is missing" in audit.blockers
    assert "rollback: verified receipt is missing" in audit.blockers
    assert "uninstall: verified receipt is missing" in audit.blockers


def test_checksum_must_match_an_artifact_and_have_a_sha256_receipt():
    audit = ReleaseHandoffContract(
        artifacts=(ArtifactEvidence("app.exe", "artifact-receipt"),),
        checksums=(ChecksumEvidence("other.exe", SHA256, "checksum-receipt"),),
    ).audit()

    assert "checksums: entry is not tied to a required artifact (other.exe)" in audit.blockers
    assert "checksums: missing checksum for app.exe" in audit.blockers


def test_enabled_default_off_integration_is_blocked():
    audit = ReleaseHandoffContract(
        default_off_integrations=tuple(
            DefaultOffIntegrationEvidence(
                name,
                enabled=(name == "google"),
                receipt=f"receipt-{name}",
                status=EvidenceStatus.VERIFIED,
            )
            for name in DEFAULT_OFF_INTEGRATIONS
        )
    ).audit()

    assert "default-off integration: google is enabled" in audit.blockers
    assert "default-off:stripe" in audit.verified_checks


def test_json_receipt_is_deterministic_and_exposes_the_boundary():
    audit = audit_release_handoff(_complete_contract())
    payload = audit.as_dict()

    assert payload["readiness"] == "blocked"
    assert payload["clean_machine_release_proof"] == "not_proven"
    assert "clean-machine release proof" in audit.to_json()
    assert audit.to_json() == audit.to_json()
