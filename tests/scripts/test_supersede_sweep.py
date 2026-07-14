from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import check_supersede_sweep


MANIFEST_PATH = Path("docs/backlog/native-supersede-sweep-2026-07.yaml")


def manifest() -> dict:
    return check_supersede_sweep.load_manifest(MANIFEST_PATH)


def test_checked_in_manifest_is_100_percent_classified() -> None:
    value = manifest()
    assert check_supersede_sweep.validate_manifest(value) == []
    assert set(value["verdicts"]) == check_supersede_sweep.VALID_VERDICTS
    assert {row["verdict"] for row in value["issues"]} <= set(value["verdicts"])
    assert len(value["issues"]) == len(value["scope"]["issue_numbers"])


def test_missing_or_duplicate_scope_row_is_rejected() -> None:
    value = manifest()
    value["issues"] = value["issues"][1:]
    errors = check_supersede_sweep.validate_manifest(value)
    assert "missing classification for issue #334" in errors

    value = manifest()
    value["issues"].append(dict(value["issues"][0]))
    errors = check_supersede_sweep.validate_manifest(value)
    assert "duplicate classification for issue #334" in errors


def test_verdict_target_and_acceptance_mapping_are_fail_closed() -> None:
    value = manifest()
    value["issues"][0]["verdict"] = "close-all"
    value["issues"][0]["ac_mapping"] = ["AC-unknown"]
    errors = check_supersede_sweep.validate_manifest(value)
    assert any("invalid verdict" in error for error in errors)
    assert any("unknown acceptance criterion" in error for error in errors)

    value = manifest()
    value["issues"][0]["verdict"] = "subordinated"
    value["issues"][0]["target_issues"] = []
    errors = check_supersede_sweep.validate_manifest(value)
    assert "subordinated issue #334 must have target issues" in errors


def test_acceptance_criteria_must_all_be_mapped() -> None:
    value = manifest()
    value["acceptance_criteria"]["AC-unused"] = "must be mapped"
    errors = check_supersede_sweep.validate_manifest(value)
    assert "acceptance criterion AC-unused is not mapped" in errors


def test_anti_bulk_close_receipt_is_required() -> None:
    value = manifest()
    value["receipts"]["anti_bulk_close"]["mutation_allowed"] = True
    value["receipts"]["anti_bulk_close"]["close_operations"] = 1
    errors = check_supersede_sweep.validate_manifest(value)
    assert "anti_bulk_close mutation_allowed must be false" in errors
    assert "anti_bulk_close close_operations must be zero" in errors


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("schema_version: 1\nschema_version: 2\n", encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
        check_supersede_sweep.load_manifest(path)


def test_github_check_is_api_mockable_and_read_only() -> None:
    calls: list[tuple[str, int, str]] = []

    def fake_fetch(repo: str, issue: int, api_url: str) -> dict:
        calls.append((repo, issue, api_url))
        return {"number": issue, "assignees": [{"login": "owner"}]}

    errors = check_supersede_sweep.check_github(
        "owner/repo", manifest(), "https://mock.invalid", fake_fetch
    )
    assert errors == []
    assert len(calls) == len(manifest()["scope"]["issue_numbers"])


def test_github_unavailable_is_reported_as_unverified() -> None:
    def unavailable(_repo: str, _issue: int, _api_url: str) -> dict:
        raise OSError("offline")

    errors = check_supersede_sweep.check_github(
        "owner/repo", manifest(), "https://mock.invalid", unavailable
    )
    assert len(errors) == len(manifest()["scope"]["issue_numbers"])
    assert all(error.startswith("UNVERIFIED|") for error in errors)


def test_main_reports_expected_offline_limitations_without_mutation(capsys) -> None:
    assert check_supersede_sweep.main([]) == 0
    output = capsys.readouterr().out
    assert "read-only" in output
    assert "UNVERIFIED|" in output
