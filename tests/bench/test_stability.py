import json

from bench.stability import _variance_pct, check_stability, main


def test_variance_pct_is_zero_for_identical_values():
    assert _variance_pct([1.0, 1.0, 1.0]) == 0.0


def test_variance_pct_handles_zero_mean():
    assert _variance_pct([0.0, 0.0]) == 0.0


def test_check_stability_runs_baseline_n_times_and_reports_token_metrics():
    result = check_stability(runs=2, repeats=1, warmup=0, max_variance_pct=1000.0)

    assert result["schema"] == "simplicio.bench-stability/v1"
    assert result["runs"] == 2
    assert result["status"] == "pass"
    assert set(result["categories"]) == {
        "routine_deterministic",
        "memory_lookup",
        "code_edit",
        "single_tool",
        "fanout_tools",
        "freeform_chat",
        "frontier_escalation",
        "context_compaction",
    }
    # Token counts are deterministic across runs (no timing jitter involved).
    for metrics in result["categories"].values():
        assert metrics["input_tokens"]["variance_pct"] == 0.0


def test_check_stability_flags_violations_with_a_tight_threshold():
    result = check_stability(runs=2, repeats=1, warmup=0, max_variance_pct=0.0)

    assert result["status"] == "fail"
    assert result["violations"]
    assert result["evidence"].startswith("MEASURED|")


def test_cli_writes_json_report(tmp_path):
    out_path = tmp_path / "stability.json"

    exit_code = main([
        "--runs",
        "2",
        "--repeats",
        "1",
        "--warmup",
        "0",
        "--max-variance-pct",
        "1000",
        "--json",
        str(out_path),
    ])

    assert exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"


def test_cli_prints_to_stdout_and_returns_failure_exit_code(capsys):
    exit_code = main(["--runs", "2", "--repeats", "1", "--warmup", "0", "--max-variance-pct", "0"])

    assert exit_code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
