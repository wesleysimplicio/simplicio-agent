"""Focused contracts for the bounded issue #195 release-gate slice."""

from __future__ import annotations

import json
from pathlib import Path

from tools.release_gate import (
    EVIDENCE_SCHEMA,
    EXPANDED_SCHEMA,
    MATRIX_SCHEMA,
    REPO_ROOT,
    REPORT_SCHEMA,
    ROLLBACK_SCHEMA,
    build_artifact_descriptor,
    build_environment_descriptor,
    build_evidence_bundle,
    build_evidence_record,
    build_rollback_evidence,
    evaluate_release_gate,
    expand_matrix,
    main,
    validate_evidence_bundle,
    validate_matrix,
    validate_rollback_evidence,
)

FIXTURE_DIR = REPO_ROOT / "fixtures" / "release-matrix"
MATRIX_FIXTURE = FIXTURE_DIR / "release-matrix.v1.json"
EVIDENCE_FIXTURE = FIXTURE_DIR / "release-evidence.v1.json"


def _sample_matrix() -> dict[str, object]:
    return {
        "schema": MATRIX_SCHEMA,
        "version": 1,
        "name": "bounded-release-gate",
        "axes": [
            {
                "name": "os",
                "values": [
                    {"id": "linux-x86_64", "tier": "required"},
                    {"id": "macos-arm64", "tier": "experimental"},
                ],
            },
            {"name": "channel", "values": [{"id": "wheel", "tier": "required"}]},
            {
                "name": "scenario",
                "values": [
                    {"id": "clean-install", "tier": "required"},
                    {"id": "rollback", "tier": "required"},
                ],
            },
            {"name": "runtime", "values": [{"id": "healthy", "tier": "required"}]},
        ],
        "exclude": [{"when": {"os": "macos-arm64", "scenario": "rollback"}}],
    }


def test_expand_matrix_is_deterministic_and_classifies_required_cases() -> None:
    matrix = _sample_matrix()
    first = expand_matrix(matrix)
    second = expand_matrix(matrix)
    assert first == second
    assert first["schema"] == EXPANDED_SCHEMA
    assert first["summary"] == {"case_count": 3, "required": 2, "experimental": 1}
    assert [case["id"] for case in first["cases"]] == [
        "os=linux-x86_64__channel=wheel__scenario=clean-install__runtime=healthy",
        "os=linux-x86_64__channel=wheel__scenario=rollback__runtime=healthy",
        "os=macos-arm64__channel=wheel__scenario=clean-install__runtime=healthy",
    ]
    rollback_case = first["cases"][1]
    assert rollback_case["required_evidence"] == [
        "artifact",
        "environment",
        "receipts",
        "rollback",
    ]


def test_environment_and_artifact_evidence_records_are_digest_pinned() -> None:
    artifact = build_artifact_descriptor(
        name="simplicio-agent-0.25.0-py3-none-any.whl",
        channel="wheel",
        kind="wheel",
        digest="sha256:" + "a" * 64,
        source_uri="https://example.invalid/wheel",
    )
    environment = build_environment_descriptor(
        runner="gha-ubuntu-24.04",
        clean_room=True,
        cache_scope="job",
        manifest={"python": "3.13.5", "image": "ubuntu@sha256:" + "b" * 64},
    )
    assert artifact["digest"].startswith("sha256:")
    assert environment["manifest_digest"].startswith("sha256:")
    mutated = dict(environment)
    mutated["manifest"] = {"python": "3.13.6"}
    record = build_evidence_record(
        case_id="os=linux-x86_64__channel=wheel__scenario=clean-install__runtime=healthy",
        tier="required",
        status="pass",
        artifact=artifact,
        environment=mutated,
        receipts=["doctor.json"],
    )
    bundle = build_evidence_bundle(_sample_matrix(), [record])
    errors = validate_evidence_bundle(bundle, _sample_matrix())
    assert "records[0].environment.manifest_digest mismatch" in errors


def test_rollback_schema_is_required_for_rollback_cases() -> None:
    matrix = _sample_matrix()
    expanded = expand_matrix(matrix)
    clean_case = expanded["cases"][0]["id"]
    rollback_case = expanded["cases"][1]["id"]
    artifact = build_artifact_descriptor(
        name="bundle.zip",
        channel="wheel",
        kind="bundle",
        digest="sha256:" + "c" * 64,
        source_uri="https://example.invalid/bundle",
    )
    environment = build_environment_descriptor(
        runner="gha-ubuntu-24.04",
        clean_room=True,
        cache_scope="job",
        manifest={"python": "3.13.5"},
    )
    good_rollback = build_rollback_evidence(
        from_release="0.24.0",
        to_release="0.25.0",
        restored_release="0.24.0",
        restored_artifact_digest="sha256:" + "d" * 64,
        state_preserved=True,
        receipts=["rollback.json"],
    )
    assert validate_rollback_evidence(good_rollback) == []
    incomplete = dict(good_rollback)
    incomplete["schema"] = "wrong"
    assert "rollback.schema must be simplicio.release-rollback-evidence/v1" in validate_rollback_evidence(incomplete)
    bundle = build_evidence_bundle(
        matrix,
        [
            build_evidence_record(
                case_id=clean_case,
                tier="required",
                status="pass",
                artifact=artifact,
                environment=environment,
                receipts=["clean.json"],
            ),
            build_evidence_record(
                case_id=rollback_case,
                tier="required",
                status="pass",
                artifact=artifact,
                environment=environment,
                receipts=["rollback.json"],
            ),
        ],
    )
    errors = validate_evidence_bundle(bundle, matrix)
    assert "records[1].rollback is required for rollback scenarios" in errors


def test_required_tier_evaluation_is_fail_closed_on_missing_required_case() -> None:
    matrix = _sample_matrix()
    clean_case = expand_matrix(matrix)["cases"][0]["id"]
    artifact = build_artifact_descriptor(
        name="bundle.zip",
        channel="wheel",
        kind="bundle",
        digest="sha256:" + "e" * 64,
        source_uri="https://example.invalid/bundle",
    )
    environment = build_environment_descriptor(
        runner="gha-ubuntu-24.04",
        clean_room=True,
        cache_scope="job",
        manifest={"python": "3.13.5"},
    )
    evidence = build_evidence_bundle(
        matrix,
        [
            build_evidence_record(
                case_id=clean_case,
                tier="required",
                status="pass",
                artifact=artifact,
                environment=environment,
                receipts=["clean.json"],
            )
        ],
    )
    report = evaluate_release_gate(matrix, evidence)
    assert report["schema"] == REPORT_SCHEMA
    assert report["required"]["ok"] is False
    assert report["summary"]["stable_promotion"] == "block"
    assert report["required"]["missing"] == [
        "os=linux-x86_64__channel=wheel__scenario=rollback__runtime=healthy"
    ]


def test_fixtures_are_valid_and_required_tier_green() -> None:
    assert MATRIX_FIXTURE.is_file()
    assert EVIDENCE_FIXTURE.is_file()
    matrix = json.loads(MATRIX_FIXTURE.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    assert validate_matrix(matrix) == []
    assert evidence["schema"] == EVIDENCE_SCHEMA
    assert validate_evidence_bundle(evidence, matrix) == []
    report = evaluate_release_gate(matrix, evidence)
    assert report["required"]["ok"] is True
    assert report["experimental"]["observed"] == 1
    assert report["summary"]["stable_promotion"] == "allow"


def test_cli_expand_and_evaluate_fixture_documents(tmp_path: Path) -> None:
    expanded = tmp_path / "expanded.json"
    report = tmp_path / "report.json"
    assert main(["expand", str(MATRIX_FIXTURE), "--write", str(expanded)]) == 0
    assert json.loads(expanded.read_text(encoding="utf-8"))["schema"] == EXPANDED_SCHEMA
    assert main(["validate-matrix", str(MATRIX_FIXTURE)]) == 0
    assert main(["validate-evidence", str(MATRIX_FIXTURE), str(EVIDENCE_FIXTURE)]) == 0
    assert main(["evaluate", str(MATRIX_FIXTURE), str(EVIDENCE_FIXTURE), "--write", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["schema"] == REPORT_SCHEMA
