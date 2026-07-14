import json
from copy import deepcopy

import pytest

from bench.harness import (
    DEFAULT_FIXTURES,
    REPORT_SCHEMA,
    _percentile,
    case_digest,
    compare_reports,
    load_manifest,
    run_benchmark,
    scan_sensitive,
    validate_report,
    RECEIPT_SCHEMA,
    main,
)


def test_manifest_is_versioned_content_addressed_and_balanced():
    manifest = load_manifest()

    assert manifest["schema"] == "simplicio.bench-fixture/v1"
    assert len(manifest["categories"]) >= 8
    assert len(manifest["cases"]) >= 40
    assert sum(category["weight"] for category in manifest["categories"]) == 100
    assert all(case["id"] == case_digest(case) for case in manifest["cases"])
    assert not scan_sensitive(manifest["cases"])


def test_percentile_uses_nearest_rank_for_small_samples():
    values = [1.0, 2.0, 3.0, 4.0]

    assert _percentile(values, 0.50) == 2.0
    assert _percentile(values, 0.95) == 4.0
    with pytest.raises(ValueError):
        _percentile([], 0.50)


def test_stub_report_has_token_latency_and_memory_metrics():
    report = run_benchmark(repeats=2, warmup=0)

    assert report["schema"] == REPORT_SCHEMA
    assert report["provider"] == "stub"
    assert report["sample_count"] == 80
    assert report["fixture_sha256"]
    assert len(report["categories"]) == 8
    for category in report["categories"]:
        assert category["sample_count"] == 10
        assert category["input_tokens"] > 0
        assert category["output_tokens"] > 0
        assert category["latency_us"]["p50"] <= category["latency_us"]["p95"]
        assert category["peak_memory_bytes"] > 0


def test_report_is_a_versioned_receipt_and_validates_against_manifest():
    report = run_benchmark(repeats=1, warmup=0)

    assert report["receipt_schema"] == RECEIPT_SCHEMA
    assert validate_report(report, load_manifest()) == []
    assert report["evidence"].startswith("MEASURED|")


def test_before_after_comparator_gates_token_and_latency_regressions():
    before = run_benchmark(repeats=1, warmup=0)
    after = deepcopy(before)
    after["categories"][0]["input_tokens"] *= 1.20
    after["categories"][0]["latency_us"]["p95"] *= 1.50

    result = compare_reports(before, after, manifest=load_manifest())

    assert result["status"] == "blocked"
    assert "routine_deterministic.input_tokens" in result["regressions"]
    assert "routine_deterministic.latency_us.p95" in result["regressions"]
    assert result["summary"]["metric_count"] == 32


def test_before_after_comparator_fails_closed_on_receipt_mismatch():
    before = run_benchmark(repeats=1, warmup=0)
    after = deepcopy(before)
    after["fixture_sha256"] = "sha256:different"
    del after["categories"][-1]

    result = compare_reports(before, after, manifest=load_manifest())

    assert result["status"] == "blocked"
    assert "before and after fixture_sha256 values must match" in result["errors"]
    assert any(
        "report categories must cover every fixture category" in error
        for error in result["errors"]
    )


def test_unverified_receipt_provenance_is_preserved_in_gate():
    before = run_benchmark(repeats=1, warmup=0)
    after = deepcopy(before)
    after["evidence"] = "UNVERIFIED|synthetic before-after input"

    result = compare_reports(before, after, manifest=load_manifest())

    assert result["status"] == "pass"
    assert result["evidence"].startswith("UNVERIFIED|")


def test_compare_cli_is_reusable_and_writes_gate_receipt(tmp_path):
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    gate_path = tmp_path / "gate.json"
    report = run_benchmark(repeats=1, warmup=0)
    rendered = json.dumps(report)
    before_path.write_text(rendered, encoding="utf-8")
    after_path.write_text(rendered, encoding="utf-8")

    assert (
        main([
            "compare",
            "--before",
            str(before_path),
            "--after",
            str(after_path),
            "--json",
            str(gate_path),
        ])
        == 0
    )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["schema"] == "simplicio.bench-gate/v1"
    assert gate["status"] == "pass"


def test_report_shape_is_reusable_across_runs():
    first = run_benchmark(repeats=1, warmup=0)
    second = run_benchmark(repeats=1, warmup=0)

    stable_keys = (
        "schema",
        "fixture_set",
        "fixture_sha256",
        "provider",
        "token_estimator",
    )
    assert {key: first[key] for key in stable_keys} == {
        key: second[key] for key in stable_keys
    }
    assert [row["id"] for row in first["categories"]] == [
        row["id"] for row in second["categories"]
    ]
    assert [row["route"] for row in first["categories"]] == [
        row["route"] for row in second["categories"]
    ]


def test_manifest_rejects_modified_content_address(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["cases"][0]["input"]["prompt"] = "changed"
    modified = tmp_path / "manifest.json"
    modified.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="content address"):
        load_manifest(modified)
