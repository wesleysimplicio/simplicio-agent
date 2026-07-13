"""Focused tests for the deterministic local benchmark-program slice (#23)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.benchmark_program import (
    DEFAULT_BASELINE,
    DEFAULT_CANDIDATE,
    DEFAULT_MANIFEST,
    compare_reports,
    main,
    validate_manifest,
    validate_report,
)


def fixture(name: str) -> dict:
    path = {
        "manifest": DEFAULT_MANIFEST,
        "baseline": DEFAULT_BASELINE,
        "candidate": DEFAULT_CANDIDATE,
    }[name]
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_is_versioned_local_only_and_declares_stage_budgets() -> None:
    manifest = fixture("manifest")

    assert validate_manifest(manifest) == []
    assert manifest["schema"].endswith("/v1")
    assert manifest["execution"] == {
        "mode": "synthetic_fixture",
        "network": "disabled",
        "capability_claims": False,
    }
    assert all(stage["budgets"] for stage in manifest["stages"])
    assert all(stage["metrics"] for stage in manifest["stages"])


def test_manifest_validation_rejects_undeclared_budget_and_network() -> None:
    manifest = fixture("manifest")
    manifest["execution"]["network"] = "internet"
    manifest["stages"][0]["metrics"][0]["budget_key"] = "missing"

    errors = validate_manifest(manifest)

    assert "execution.network must be disabled" in errors
    assert any("budget_key must reference a declared budget" in error for error in errors)


def test_reports_are_local_fixture_receipts_and_validate_against_manifest() -> None:
    manifest = fixture("manifest")
    baseline = fixture("baseline")
    candidate = fixture("candidate")

    assert validate_report(baseline, manifest) == []
    assert validate_report(candidate, manifest) == []
    assert all(case["status"] == "pass" for case in baseline["cases"])


def test_comparison_passes_within_tolerance_and_is_deterministic() -> None:
    manifest = fixture("manifest")
    baseline = fixture("baseline")
    candidate = fixture("candidate")

    first = compare_reports(manifest, baseline, candidate)
    second = compare_reports(manifest, baseline, copy.deepcopy(candidate))

    assert first == second
    assert first["status"] == "pass"
    assert first["summary"] == {
        "metric_count": 12,
        "regression_count": 0,
        "budget_violation_count": 0,
    }
    assert first["limitations"]


def test_comparison_blocks_metric_regression() -> None:
    manifest = fixture("manifest")
    baseline = fixture("baseline")
    candidate = fixture("candidate")
    candidate["cases"][0]["stages"][1]["metrics"]["duration_ms"] = 40

    result = compare_reports(manifest, baseline, candidate)

    assert result["status"] == "blocked"
    assert "local.echo.execute.duration_ms" in result["regressions"]


def test_comparison_blocks_declared_budget_overrun() -> None:
    manifest = fixture("manifest")
    baseline = fixture("baseline")
    candidate = fixture("candidate")
    candidate["cases"][1]["stages"][1]["metrics"]["duration_ms"] = 251

    result = compare_reports(manifest, baseline, candidate)

    assert result["status"] == "blocked"
    assert "local.sort.execute.duration_ms=251>250" in result["budget_violations"]


def test_cli_validates_and_writes_comparison_receipt(tmp_path: Path) -> None:
    output = tmp_path / "gate.json"

    assert main(["validate-manifest", "--manifest", str(DEFAULT_MANIFEST)]) == 0
    assert (
        main([
            "compare",
            "--manifest",
            str(DEFAULT_MANIFEST),
            "--baseline",
            str(DEFAULT_BASELINE),
            "--candidate",
            str(DEFAULT_CANDIDATE),
            "--output",
            str(output),
            "--json",
        ])
        == 0
    )
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["schema"].endswith("/v1")
    assert receipt["status"] == "pass"
