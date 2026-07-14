"""Focused tests for the bounded issue #135 support-bundle contract."""

from __future__ import annotations

import json

import pytest

from agent.support_bundle_contract import (
    ArtifactKind,
    ArtifactStatus,
    BundleStatus,
    DoctorEvidence,
    DoctorStatus,
    EnvironmentMetadata,
    SupportArtifact,
    SupportBundleContract,
    build_support_bundle,
    redact_mapping,
    sha256_bytes,
    sha256_text,
)


SHA256 = "a" * 64


def _complete_bundle():
    environment = EnvironmentMetadata(
        os_name="Windows",
        architecture="amd64",
        python_version="3.11.9",
        agent_version="0.25.0",
        runtime_version="3.5.2",
        capabilities=("doctor-json", "backup-receipt"),
    )
    artifacts = tuple(
        SupportArtifact(
            kind=kind,
            name=f"{kind.value}-artifact",
            version="1.0.0",
            sha256=SHA256,
            status=ArtifactStatus.VERIFIED,
            evidence_ids=(f"evidence-{kind.value}",),
        )
        for kind in ArtifactKind
    )
    return build_support_bundle(
        environment=environment,
        artifacts=artifacts,
        doctor=DoctorEvidence(
            status=DoctorStatus.PASS,
            checks=("runtime", "configuration"),
            evidence_ids=("doctor-evidence",),
        ),
        configuration={"provider": "local", "api_key": "super-secret-token"},
        recent_errors=("safe error",),
        evidence_ids=("bundle-evidence",),
    )


def test_empty_contract_is_explicitly_incomplete_and_has_no_workflow_claim():
    bundle = SupportBundleContract().build()

    assert bundle.status is BundleStatus.INCOMPLETE
    assert bundle.is_complete is False
    assert "environment metadata is missing" in bundle.incomplete_reasons
    assert "doctor evidence is missing" in bundle.incomplete_reasons
    assert "verified install artifact checksum is missing" in bundle.incomplete_reasons
    assert "installer" not in bundle.to_json().lower()


def test_complete_receipt_models_all_four_artifacts_and_environment():
    bundle = _complete_bundle()
    payload = bundle.as_dict()

    assert bundle.status is BundleStatus.COMPLETE
    assert {item["kind"] for item in payload["artifacts"]} == {
        "install",
        "doctor",
        "backup",
        "support",
    }
    assert payload["environment"]["architecture"] == "amd64"
    assert payload["doctor"]["status"] == "pass"
    assert payload["incomplete_reasons"] == []


def test_configuration_errors_and_ids_never_expose_secrets_or_personal_paths():
    bundle = build_support_bundle(
        environment=EnvironmentMetadata("Linux", "x86_64"),
        configuration={
            "api_key": "super-secret-token",
            "nested": {"password": "correct horse battery staple"},
            "home": r"C:\Users\alice\private\config.yaml",
            "prompt": "do not include this prompt",
        },
        recent_errors=("token=secret-value at C:/Users/alice/app",),
        evidence_ids=("Bearer very-secret-token-value",),
    )
    serialized = bundle.to_json()

    assert "super-secret-token" not in serialized
    assert "correct horse battery staple" not in serialized
    assert "secret-value" not in serialized
    assert "alice" not in serialized
    assert "do not include this prompt" not in serialized
    assert bundle.redactions_applied > 0
    assert "prompt" not in bundle.as_dict()["configuration"]


def test_redactor_recurses_and_excludes_content_without_collecting_it():
    value = redact_mapping(
        {
            "safe": {"count": 2},
            "token": "raw-token",
            "response": "model response must not be copied",
            "path": r"C:\Users\bob\workspace\file.txt",
        }
    )

    assert value["safe"] == {"count": 2}
    assert value["token"] == "[REDACTED]"
    assert "response" not in value
    assert value["path"] == "[REDACTED_PATH]"


def test_checksums_are_sha256_and_invalid_artifact_checksum_is_rejected():
    assert sha256_bytes(b"support") == sha256_text("support")
    with pytest.raises(ValueError, match="64-character"):
        SupportArtifact(ArtifactKind.SUPPORT, "receipt", sha256="not-a-checksum")


def test_unverified_and_missing_artifacts_keep_bundle_incomplete():
    bundle = build_support_bundle(
        environment=EnvironmentMetadata("macOS", "arm64"),
        artifacts=(
            SupportArtifact(
                ArtifactKind.INSTALL,
                "installer",
                sha256=SHA256,
                status=ArtifactStatus.DECLARED,
            ),
        ),
        doctor=DoctorEvidence(
            status=DoctorStatus.WARN,
            evidence_ids=("doctor-evidence",),
        ),
    )

    assert bundle.status is BundleStatus.INCOMPLETE
    assert "verified install artifact checksum is missing" in bundle.incomplete_reasons
    assert sum("artifact checksum is missing" in reason for reason in bundle.incomplete_reasons) == 4


def test_json_is_deterministic_and_only_contains_bounded_fields():
    first = _complete_bundle()
    second = _complete_bundle()

    assert first.to_json() == second.to_json()
    payload = json.loads(first.to_json())
    assert set(payload) == {
        "artifacts",
        "configuration",
        "doctor",
        "environment",
        "evidence_ids",
        "incomplete_reasons",
        "issue_number",
        "redactions_applied",
        "schema",
        "status",
        "recent_errors",
    }
    assert "content" not in first.to_json().lower()
