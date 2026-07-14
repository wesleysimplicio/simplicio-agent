import json

import pytest

from bench.harness import (
    DEFAULT_FIXTURES,
    REPORT_SCHEMA,
    _percentile,
    case_digest,
    load_manifest,
    run_benchmark,
    scan_sensitive,
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
