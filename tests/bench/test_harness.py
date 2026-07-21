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


def _valid_report():
    return run_benchmark(repeats=1, warmup=0)


def test_validate_report_flags_missing_schema_and_evidence_fields():
    errors = validate_report({})

    assert "schema must be simplicio.bench-report/v1" in errors
    assert "receipt_schema must be simplicio.bench-receipt/v1" in errors
    assert "evidence must start with MEASURED| or UNVERIFIED|" in errors
    assert "categories must be a non-empty list" in errors


def test_validate_report_rejects_non_positive_repeats_and_bad_ints():
    report = _valid_report()
    report["repeats"] = 0
    report["warmup"] = -1
    report["sample_count"] = True

    errors = validate_report(report)

    assert "repeats must be positive" in errors
    assert "warmup must be a non-negative integer" in errors
    assert "sample_count must be a non-negative integer" in errors


def test_validate_report_rejects_malformed_category_rows():
    report = _valid_report()
    report["categories"] = [
        "not-an-object",
        {"id": ""},
        {
            "id": "extra_unknown_category",
            "weight_pct": -1,
            "input_tokens": -1,
            "output_tokens": -1,
            "peak_memory_bytes": -1,
            "latency_us": "not-a-mapping",
            "sample_count": 0,
        },
    ]

    errors = validate_report(report, load_manifest())

    assert "categories[0] must be an object" in errors
    assert "categories[1].id must be a non-empty string" in errors
    assert "categories[2].id is not in the fixture manifest" in errors
    assert "categories[2].weight_pct must be a non-negative number" in errors
    assert "categories[2].latency_us must be an object" in errors
    assert "categories[2].sample_count must be a positive integer" in errors


def test_validate_report_rejects_weight_route_and_percentile_mismatch():
    report = _valid_report()
    manifest = load_manifest()
    row = report["categories"][0]
    row["weight_pct"] = row["weight_pct"] + 1
    row["route"] = "wrong-route"
    row["latency_us"]["p50"] = 100
    row["latency_us"]["p95"] = 50

    errors = validate_report(report, manifest)

    assert any("weight_pct must match the fixture manifest" in e for e in errors)
    assert any("route must match the fixture manifest" in e for e in errors)
    assert any("p50 must not exceed p95" in e for e in errors)


def test_validate_report_rejects_duplicate_ids_missing_categories_and_bad_total():
    report = _valid_report()
    manifest = load_manifest()
    report["categories"][1]["id"] = report["categories"][0]["id"]
    report["sample_count"] = -5
    report["fixture_set"] = "different-set"

    errors = validate_report(report, manifest)

    assert "report category ids must be unique" in errors
    assert "sample_count must be a non-negative integer" in errors
    assert "fixture_set must match the fixture manifest" in errors


def test_compare_reports_rejects_bad_thresholds_and_missing_category():
    before = _valid_report()
    after = deepcopy(before)
    del after["categories"][0]

    result = compare_reports(
        before, after, token_threshold_pct=-1, latency_threshold_pct=-1
    )

    assert result["status"] == "blocked"
    assert "token_threshold_pct must be a non-negative number" in result["errors"]
    assert "latency_threshold_pct must be a non-negative number" in result["errors"]
    assert any("must be present in both receipts" in e for e in result["errors"])


def test_compare_reports_rejects_non_numeric_metric_values():
    before = _valid_report()
    after = deepcopy(before)
    after["categories"][0]["input_tokens"] = "not-a-number"

    result = compare_reports(before, after)

    assert result["status"] == "blocked"
    assert any("must be numeric in both receipts" in e for e in result["errors"])


def test_compare_reports_handles_zero_before_value_as_regression_when_after_positive():
    before = _valid_report()
    after = deepcopy(before)
    before["categories"][0]["input_tokens"] = 0
    after["categories"][0]["input_tokens"] = 5

    result = compare_reports(before, after)

    assert "routine_deterministic.input_tokens" in result["regressions"]


def test_load_manifest_rejects_bad_schema(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": "bogus"}), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported fixture schema"):
        load_manifest(path)


def test_load_manifest_rejects_too_few_categories(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["categories"] = data["categories"][:2]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="at least eight unique categories"):
        load_manifest(path)


def test_load_manifest_rejects_bad_weight_total(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["categories"][0]["weight"] += 1
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="weights must sum to 100"):
        load_manifest(path)


def test_load_manifest_rejects_case_missing_required_fields(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    del data["cases"][0]["expected"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="requires id, category, input, and expected"):
        load_manifest(path)


def test_load_manifest_rejects_unknown_case_category(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["cases"][0]["category"] = "not_a_real_category"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown case category"):
        load_manifest(path)


def test_load_manifest_rejects_route_mismatch(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["cases"][0]["expected"]["route"] = "wrong-route"
    data["cases"][0]["id"] = case_digest(data["cases"][0])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="route mismatch"):
        load_manifest(path)


def test_load_manifest_rejects_sensitive_case_data(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["cases"][0]["input"]["prompt"] = "contact me at person@example.com"
    data["cases"][0]["id"] = case_digest(data["cases"][0])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="sensitive data detected in case"):
        load_manifest(path)


def test_load_manifest_rejects_too_few_cases_per_category(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["cases"] = [
        case
        for case in data["cases"]
        if case["category"] != "routine_deterministic" or case["id"] != data["cases"][0]["id"]
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="at least five cases"):
        load_manifest(path)


def test_run_benchmark_rejects_non_stub_provider_and_bad_repeats():
    with pytest.raises(ValueError, match="provider stub"):
        run_benchmark(provider="local")
    with pytest.raises(ValueError, match="repeats must be positive"):
        run_benchmark(repeats=0)
    with pytest.raises(ValueError, match="repeats must be positive"):
        run_benchmark(warmup=-1)


def test_cli_run_prints_report_to_stdout_when_no_json_path(capsys):
    exit_code = main(["run", "--repeats", "1", "--warmup", "0"])

    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == REPORT_SCHEMA


def test_cli_compare_prints_gate_to_stdout_when_no_json_path(tmp_path, capsys):
    report = _valid_report()
    before_path = tmp_path / "before.json"
    before_path.write_text(json.dumps(report), encoding="utf-8")

    exit_code = main(["compare", "--before", str(before_path), "--after", str(before_path)])

    assert exit_code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "simplicio.bench-gate/v1"
    assert out["status"] == "blocked"


def test_cli_compare_returns_error_exit_code_on_unreadable_input(tmp_path, capsys):
    missing_path = tmp_path / "missing.json"

    exit_code = main([
        "compare",
        "--before",
        str(missing_path),
        "--after",
        str(missing_path),
    ])

    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_compare_returns_regression_exit_code(tmp_path):
    before = _valid_report()
    after = deepcopy(before)
    after["categories"][0]["input_tokens"] *= 2
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps(before), encoding="utf-8")
    after_path.write_text(json.dumps(after), encoding="utf-8")

    exit_code = main([
        "compare",
        "--before",
        str(before_path),
        "--after",
        str(after_path),
    ])

    assert exit_code == 1


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
        assert category["latency_us"] == {"p50": None, "p95": None}
        assert category["peak_memory_bytes"] is None
        assert category["metric_evidence"]["latency_us"].startswith("UNVERIFIED|")


def test_report_is_a_versioned_receipt_and_validates_against_manifest():
    report = run_benchmark(repeats=1, warmup=0)

    assert report["receipt_schema"] == RECEIPT_SCHEMA
    assert validate_report(report, load_manifest()) == []
    assert report["evidence"].startswith("UNVERIFIED|")


def test_before_after_comparator_gates_token_and_latency_regressions():
    before = run_benchmark(repeats=1, warmup=0)
    after = deepcopy(before)
    after["categories"][0]["input_tokens"] *= 1.20
    for receipt in (before, after):
        receipt["categories"][0]["latency_us"] = {"p50": 10, "p95": 10}
        receipt["categories"][0]["metric_evidence"]["latency_us"] = (
            "MEASURED|executor timing supplied by test receipt"
        )
    after["categories"][0]["latency_us"]["p95"] *= 1.50

    result = compare_reports(before, after, manifest=load_manifest())

    assert result["status"] == "blocked"
    assert "routine_deterministic.input_tokens" in result["regressions"]
    assert "routine_deterministic.latency_us.p95" in result["regressions"]
    assert result["summary"]["metric_count"] == 18


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

    assert result["status"] == "blocked"
    assert any("latency_us.p50 is unavailable" in error for error in result["errors"])
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
        == 1
    )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["schema"] == "simplicio.bench-gate/v1"
    assert gate["status"] == "blocked"


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


def test_stub_report_is_byte_for_byte_deterministic_and_offline(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("stub attempted network access")
    ))

    first = run_benchmark(repeats=2, warmup=1)
    second = run_benchmark(repeats=2, warmup=1)

    assert first == second


def test_manifest_rejects_modified_content_address(tmp_path):
    data = json.loads(DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    data["cases"][0]["input"]["prompt"] = "changed"
    modified = tmp_path / "manifest.json"
    modified.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="content address"):
        load_manifest(modified)
