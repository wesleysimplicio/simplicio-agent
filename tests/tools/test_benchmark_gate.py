"""Focused contract tests for issue #157's deterministic gate slice."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.benchmark_gate import (
    DEFAULT_MANIFEST,
    contract_smoke,
    evaluate_gate,
    main,
    validate_manifest,
    validate_report,
)


def manifest() -> dict:
    return json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))


def metric(kind: str = "measured", value: int = 1) -> dict:
    return {
        "value": value,
        "unit": "boolean",
        "evidence_kind": kind,
        "source": "fixture:test",
    }


def artifact(name: str = "run.log") -> dict:
    return {
        "kind": "log",
        "path": f"artifacts/{name}",
        "sha256": "a" * 64,
        "sanitized": True,
        "redactions": ["credentials"],
    }


def report(manifest_doc: dict, *, kind: str = "measured", mode: str = "smoke") -> dict:
    rows = []
    for suite in manifest_doc["suites"]:
        for task in suite["tasks"]:
            rows.append({
                "task_id": task["id"],
                "status": "pass",
                "evidence_kind": kind,
                "metrics": {"task_success": metric(kind)},
                "artifacts": [],
            })
    return {
        "schema": "simplicio.capability-benchmark-report/v1",
        "version": 1,
        "manifest_id": manifest_doc["manifest_id"],
        "run_mode": mode,
        "runner": {"platform": "windows", "os": "Windows", "hardware": "fixture"},
        "tasks": rows,
    }


def test_manifest_is_versioned_and_declares_all_required_suites() -> None:
    document = manifest()
    assert validate_manifest(document) == []
    assert document["schema"].endswith("/v1")
    assert {suite["id"] for suite in document["suites"]} == {
        "desktop",
        "browser",
        "coding",
        "media",
        "office",
        "mobile",
        "persistent-run",
    }


def test_manifest_validation_is_deterministic_and_requires_task_contract() -> None:
    document = manifest()
    document["suites"][0]["tasks"][0].pop("verifier")
    first = validate_manifest(document)
    second = validate_manifest(copy.deepcopy(document))
    assert first == second
    assert "suites[0].tasks[0].verifier must be a non-empty string" in first


def test_contract_smoke_validates_only_the_manifest_and_makes_no_capability_claim() -> (
    None
):
    result = contract_smoke(manifest())
    assert result["status"] == "contract_pass"
    assert result["executed_task_count"] == 0
    assert result["release_ready"] is False
    assert result["claims"] == []
    assert any("No desktop" in limitation for limitation in result["limitations"])


def test_measured_smoke_results_pass_but_do_not_release_without_full_mode() -> None:
    document = manifest()
    result = evaluate_gate(document, report(document, mode="smoke"))
    assert result["smoke_ready"] is True
    assert result["release_ready"] is False
    assert "full_matrix_not_executed" in result["reasons"]


def test_estimated_success_never_satisfies_the_gate() -> None:
    document = manifest()
    receipt = report(document, kind="estimated", mode="release")
    result = evaluate_gate(document, receipt)
    assert result["smoke_ready"] is False
    assert result["release_ready"] is False
    assert result["unmeasured_task_ids"]
    assert result["estimated_metric_count"] == len(receipt["tasks"])


def test_report_must_match_the_manifest_identity() -> None:
    document = manifest()
    receipt = report(document)
    receipt["manifest_id"] = "different-manifest"
    assert "manifest_id must match the manifest" in validate_report(receipt, document)


def test_measured_full_matrix_can_release() -> None:
    document = manifest()
    result = evaluate_gate(document, report(document, mode="release"))
    assert result["release_ready"] is True
    assert result["status"] == "pass"
    assert result["reasons"] == []


def test_failed_or_blocked_results_require_sanitized_hashed_artifacts() -> None:
    document = manifest()
    receipt = report(document)
    row = receipt["tasks"][0]
    row["status"] = "blocked"
    row["blocked_reason"] = "missing_permission"
    assert validate_report(receipt, document)[0].endswith(
        "must be non-empty for blocked results"
    )
    row["artifacts"] = [artifact("blocked.log")]
    assert validate_report(receipt, document) == []
    row["artifacts"][0]["sanitized"] = False
    assert any(
        "sanitized must be true" in error
        for error in validate_report(receipt, document)
    )


def test_cli_smoke_writes_stable_contract_receipt(tmp_path: Path) -> None:
    output = tmp_path / "smoke.json"
    assert (
        main([
            "smoke",
            "--manifest",
            str(DEFAULT_MANIFEST),
            "--output",
            str(output),
            "--json",
        ])
        == 0
    )
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["schema"] == "simplicio.capability-release-gate/v1"
    assert receipt["executed_task_count"] == 0
