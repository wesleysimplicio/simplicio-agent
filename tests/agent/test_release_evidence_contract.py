"""Focused tests for the bounded issue #130 Desktop release evidence contract."""

from __future__ import annotations

from dataclasses import replace

from agent.release_evidence_contract import (
    CONTRACT_VERSION,
    ArtifactIdentity,
    BuildInputs,
    ChecksumEvidence,
    EvidenceStatus,
    InstallerEvidence,
    MatrixOutcome,
    MatrixResult,
    ReproducibilityEvidence,
    ReproducibilityStatus,
    ReleaseEvidenceContract,
    SignatureEvidence,
    audit_release_evidence,
)


SHA256 = "a" * 64
ARTIFACT = ArtifactIdentity(
    artifact_id="simplicio-desktop-windows-x64",
    product="simplicio",
    version="1.2.3",
    platform="windows",
    architecture="x64",
    format="msi",
)


def _complete_contract() -> ReleaseEvidenceContract:
    matrix = ("windows-x64", "macos-arm64")
    return ReleaseEvidenceContract(
        artifacts=(ARTIFACT,),
        build_inputs=BuildInputs(
            source_commit="a" * 40,
            lockfile_sha256=SHA256,
            toolchain="rust-1.82.0-node-22",
            configuration="release",
            receipt="inputs-receipt",
        ),
        installers=(
            InstallerEvidence("simplicio-desktop-windows-x64", "installer-receipt", EvidenceStatus.VERIFIED),
        ),
        checksums=(ChecksumEvidence(ARTIFACT.artifact_id, SHA256, "checksum-receipt"),),
        signatures=(
            SignatureEvidence(
                ARTIFACT.artifact_id,
                "sigstore://example",
                "sigstore-bundle",
                "signature-receipt",
                EvidenceStatus.VERIFIED,
            ),
        ),
        required_matrix=matrix,
        matrix_results=(
            MatrixResult("windows-x64", "windows", "x64", MatrixOutcome.PASS, "matrix-win"),
            MatrixResult("macos-arm64", "macos", "arm64", MatrixOutcome.PASS, "matrix-mac"),
        ),
        reproducibility=ReproducibilityEvidence(
            ReproducibilityStatus.VERIFIED,
            "reproducibility-comparison-receipt",
        ),
    )


def test_empty_contract_fails_closed_for_every_evidence_category() -> None:
    audit = ReleaseEvidenceContract().audit()

    assert audit.is_blocked
    assert not audit.is_ready
    assert not audit.evidence_complete
    assert audit.reproducibility_status is ReproducibilityStatus.NOT_PROVEN
    assert "artifacts: a non-empty bounded artifact list is required" in audit.blockers
    assert "build inputs: evidence is missing" in audit.blockers
    assert "installers: receipt evidence is missing" in audit.blockers
    assert "checksums: SHA-256 evidence is missing" in audit.blockers
    assert "signatures: verification evidence is missing" in audit.blockers
    assert "matrix: a non-empty bounded required matrix is missing" in audit.blockers
    assert audit.installer_build_claimed is False


def test_complete_receipts_pass_only_the_evidence_gate() -> None:
    audit = _complete_contract().audit()

    assert audit.evidence_complete
    assert audit.is_ready
    assert not audit.is_blocked
    assert audit.readiness == "evidence_complete"
    assert audit.reproducibility_status is ReproducibilityStatus.VERIFIED
    assert {
        "artifact:simplicio-desktop-windows-x64",
        "build-inputs",
        "installer:simplicio-desktop-windows-x64",
        "checksum:simplicio-desktop-windows-x64",
        "signature:simplicio-desktop-windows-x64",
        "matrix:windows-x64",
        "matrix:macos-arm64",
        "reproducibility",
    } == set(audit.verified_checks)
    assert audit.as_dict()["schema_version"] == CONTRACT_VERSION
    assert audit.as_dict()["installer_build_claimed"] is False


def test_missing_receipt_or_non_passing_matrix_cell_blocks() -> None:
    contract = _complete_contract()
    audit = replace(
        contract,
        installers=(InstallerEvidence(ARTIFACT.artifact_id, None, EvidenceStatus.MISSING),),
        matrix_results=(
            MatrixResult("windows-x64", "windows", "x64", MatrixOutcome.FAIL, "matrix-win"),
        ),
    ).audit()

    assert not audit.is_ready
    assert "installers: verified receipt is missing for simplicio-desktop-windows-x64" in audit.blockers
    assert "matrix: passing receipt is missing for windows-x64" in audit.blockers
    assert "matrix: missing result for macos-arm64" in audit.blockers


def test_artifact_evidence_must_be_complete_and_tied_to_every_artifact() -> None:
    second = ArtifactIdentity("second", "simplicio", "1.2.3", "linux", "x64", "appimage")
    audit = ReleaseEvidenceContract(
        artifacts=(ARTIFACT, second, second),
        installers=(InstallerEvidence("unknown", "receipt", EvidenceStatus.VERIFIED),),
        checksums=(ChecksumEvidence(ARTIFACT.artifact_id, "bad", "receipt"),),
        signatures=(),
        required_matrix=("linux-x64",),
        matrix_results=(),
        reproducibility=ReproducibilityEvidence(),
    ).audit()

    assert not audit.is_ready
    assert "artifacts: duplicate artifact identity second" in audit.blockers
    assert "installers: orphan evidence for unknown" in audit.blockers
    assert "installers: missing evidence for second" in audit.blockers
    assert "checksums: valid SHA-256 receipt is missing for simplicio-desktop-windows-x64" in audit.blockers
    assert "signatures: verification evidence is missing" in audit.blockers


def test_matrix_is_explicit_bounded_and_rejects_unexpected_duplicates() -> None:
    result = MatrixResult("windows-x64", "windows", "x64", MatrixOutcome.PASS, "receipt")
    audit = ReleaseEvidenceContract(
        artifacts=(ARTIFACT,),
        required_matrix=("windows-x64",),
        matrix_results=(result, result, MatrixResult("linux-x64", "linux", "x64", MatrixOutcome.PASS, "receipt")),
    ).audit()

    assert "matrix: duplicate result for windows-x64" in audit.blockers
    assert "matrix: unexpected result for linux-x64" in audit.blockers


def test_reproducibility_requires_verified_status_and_comparison_receipt() -> None:
    contract = _complete_contract()
    audit = replace(
        contract,
        reproducibility=ReproducibilityEvidence(
            ReproducibilityStatus.VERIFIED,
            None,
        ),
    ).audit()

    assert audit.reproducibility_status is ReproducibilityStatus.VERIFIED
    assert "reproducibility: verified status and comparison receipt are required (verified)" in audit.blockers


def test_json_and_keyword_api_are_deterministic() -> None:
    first = audit_release_evidence(_complete_contract())
    second = audit_release_evidence(_complete_contract())

    assert first.to_json() == second.to_json()
    assert '"readiness": "evidence_complete"' in first.to_json()
    assert '"installer_build_claimed": false' in first.to_json()
