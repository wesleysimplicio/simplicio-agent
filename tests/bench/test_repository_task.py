import json

import pytest

from bench.repository_task import (
    DEFAULT_MANIFEST,
    aggregate_records,
    load_manifest,
    main,
    score_record,
    validate_manifest,
)


def _record(config="agent-cache-compat", task="gaia-synthetic-multistep-001", **changes):
    value = {
        "configuration_id": config,
        "task_id": task,
        "repeat": 1,
        "status": "completed",
        "answer": "42" if task.startswith("gaia") else "validated",
        "steps": 3,
        "evidence": ["tests/bench/test_repository_task.py:receipt"],
        "validation": "passed",
    }
    value.update(changes)
    return value


def test_fixture_has_five_controlled_configurations_and_valid_manifest():
    manifest = load_manifest()
    assert len(manifest["configurations"]) == 5
    assert validate_manifest(manifest) == []
    assert all(len(item["changed_variables"]) == 1 for item in manifest["comparisons"])


def test_score_record_is_deterministic_and_marks_wrong_empty_and_timeout():
    manifest = load_manifest()
    assert score_record(_record(), manifest)["success"] is True
    assert score_record(_record(answer=""), manifest)["empty"] is True
    assert score_record(_record(status="timeout"), manifest)["timeout"] is True
    assert score_record(_record(answer="wrong"), manifest)["success"] is False


def test_aggregate_reproduces_raw_counts_and_never_uses_zero_for_unavailable_metrics():
    manifest = load_manifest()
    report = aggregate_records([_record(), _record(task="repository-task-validation-001")], manifest)
    row = report["configurations"]["agent-cache-compat"]
    assert row["sample_count"] == 2
    assert row["success_rate"] == 1.0
    assert row["metrics"]["ttft_ms"] is None
    assert row["metric_evidence"]["ttft_ms"].startswith("UNVERIFIED|")
    assert report["single_run"] is True
    assert report["statistical_claim"].startswith("UNVERIFIED|")


def test_aggregate_rejects_duplicate_records_instead_of_double_counting():
    manifest = load_manifest()
    record = _record()
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_records([record, record], manifest)


def test_manifest_rejects_controlled_comparison_with_two_changed_variables():
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["comparisons"][0]["changed_variables"] = ["agent_variant", "profile"]
    assert any("exactly one" in error for error in validate_manifest(manifest))


def test_cli_validate_and_aggregate_write_reproducible_report(tmp_path, capsys):
    results = tmp_path / "results.json"
    report_path = tmp_path / "report.json"
    results.write_text(json.dumps([_record()]), encoding="utf-8")
    assert main(["validate"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["aggregate", "--results", str(results), "--json", str(report_path)]) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema"] == "simplicio.evaluation-report/v1"
    assert report["raw_records_sha256"].startswith("sha256:")
