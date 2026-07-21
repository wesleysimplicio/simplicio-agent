"""Focused contract tests for the bounded Software Builder foundation (#151)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.software_builder_manifest import (
    OPERATORS,
    REPO_ROOT,
    SCHEMA,
    audit_integration,
    generate_manifest,
    main,
    validate_manifest,
)

FIXTURE = REPO_ROOT / "fixtures" / "software-builder" / "v1-foundation.json"


def test_manifest_is_deterministic_and_uses_v1_contracts() -> None:
    first = generate_manifest()
    second = generate_manifest()

    assert first == second
    assert first["schema"] == SCHEMA
    assert first["status"] == "fixture_only"
    assert [stage["name"] for stage in first["stages"]] == list(OPERATORS)
    assert first["task_envelope"]["state"] == "evidence_ready"
    assert first["delivery"]["status"] == "not_attempted"
    assert first["measurement"]["status"] == "not_measured"


def test_fixture_round_trips_and_validates() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert validate_manifest(document) == []
    assert document == generate_manifest()


def test_receipts_are_linked_across_goal_task_and_stages() -> None:
    document = generate_manifest()
    refs = document["receipt_refs"]

    assert [stage["receipt"] for stage in document["stages"]] == refs
    assert [item["reference"] for item in document["goal_contract"]["evidence"]] == refs
    assert document["task_envelope"]["receipts"] == refs
    assert document["task_envelope"]["evidence_refs"] == refs
    assert all(stage["verified"] is False for stage in document["stages"])


def test_validator_rejects_a_delivery_claim() -> None:
    document = generate_manifest()
    document["delivery"]["clean_machine"] = True

    errors = validate_manifest(document)

    assert any("delivery.clean_machine" in error for error in errors)


def test_validator_rejects_a_broken_receipt_edge() -> None:
    document = generate_manifest()
    document["stages"][2]["receipt"] = "receipt://wrong"

    errors = validate_manifest(document)

    assert any("receipt_refs" in error for error in errors)
    assert any("goal evidence" in error for error in errors)
    assert any("task envelope receipts" in error for error in errors)


def test_cli_generates_and_validates(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"

    assert main(["--generate", str(output)]) == 0
    assert main(["--validate", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == generate_manifest()


def test_audit_is_fail_closed_when_real_operators_are_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    receipt = audit_integration(FIXTURE)

    assert receipt["schema"] == "simplicio.software-builder-audit/v1"
    assert receipt["status"] == "UNVERIFIED"
    assert receipt["fail_closed"] is True
    assert {check["name"] for check in receipt["checks"]} == {
        "manifest",
        "mapper",
        "dev_cli",
        "runtime",
        "loop",
    }
    assert all(
        check["status"] != "PASS"
        for check in receipt["checks"]
        if check["name"] in {"mapper", "dev_cli", "runtime"}
    )


def test_audit_cli_returns_nonzero_for_unverified_run(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    assert main(["--audit", str(FIXTURE)]) == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "UNVERIFIED"
