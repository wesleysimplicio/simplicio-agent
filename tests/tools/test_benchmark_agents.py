"""Contract tests for the runtime-supervised agent benchmark (#23)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.benchmark_agents import (
    MANIFEST_SCHEMA,
    REQUIRED_AGENTS,
    compare_reports,
    run_benchmark,
    validate_manifest,
)


def _manifest(tmp_path: Path, *, runtime: list[str] | None = None) -> dict:
    stub = tmp_path / "runtime_stub.py"
    stub.write_text(
        """
import json
import subprocess
import sys

if sys.argv[1] == 'runtime':
    marker = sys.argv.index('--')
    raise SystemExit(subprocess.run(sys.argv[marker + 1:], check=False).returncode)

for event in (
    {'event': 'startup_ready', 'elapsed_ms': 2.0},
    {'event': 'ttft', 'elapsed_ms': 3.0},
    {'event': 'roundtrip', 'duration_ms': 1.0},
    {'event': 'watcher_gate', 'duration_ms': 0.5},
    {'event': 'kernel_bindings', 'duration_ms': 0.4},
    {'event': 'handles_lazy', 'duration_ms': 0.3},
    {'event': 'task_complete', 'tokens': 7, 'tokenizer': 'runtime#2775'},
):
    print(json.dumps(event), flush=True)
""",
        encoding="utf-8",
    )
    command = runtime or [sys.executable, str(stub), "runtime", "--"]
    return {
        "schema": MANIFEST_SCHEMA,
        "version": 1,
        "benchmark_id": "test-benchmark",
        "description": "test",
        "runtime": {"required": True, "command": command},
        "tokenizer": {"label": "runtime#2775"},
        "best_of_n": 2,
        "warmups": 1,
        "budgets_ms": {
            "startup_ms_p95": 100,
            "ttft_ms_p95": 100,
            "roundtrip_ms_p95": 100,
            "watcher_gate_ms_p95": 100,
            "kernel_bindings_ms_p95": 100,
            "handles_lazy_ms_p95": 100,
            "task_ms_p95": 1000,
        },
        "agents": [
            {"id": agent_id, "command": [sys.executable, str(stub), "agent"]}
            for agent_id in sorted(REQUIRED_AGENTS)
        ],
        "tasks": [
            {"id": "smoke", "args": [], "timeout_s": 5, "expected_exit_code": 0},
        ],
    }


def test_manifest_requires_the_four_agents_and_stage_budgets(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)

    assert validate_manifest(manifest) == []
    assert set(agent["id"] for agent in manifest["agents"]) == REQUIRED_AGENTS
    assert all(
        key in manifest["budgets_ms"]
        for key in (
            "watcher_gate_ms_p95",
            "kernel_bindings_ms_p95",
            "handles_lazy_ms_p95",
        )
    )


def test_runtime_supervised_runs_emit_real_receipts_and_p95(tmp_path: Path) -> None:
    report = run_benchmark(_manifest(tmp_path))

    assert report["status"] == "unverified"
    assert report["gate"]["baseline"]["reason"] == "baseline_not_provided"
    assert len(report["runs"]) == 12  # 4 agents × (1 warmup + best-of-2)
    assert len(report["aggregates"]) == 4
    for row in report["aggregates"]:
        assert row["metrics"]["ttft_ms"]["value"] == 3.0
        assert row["metrics"]["roundtrip_ms"]["value"] == 1.0
        assert row["metrics"]["tokens"]["value"] == 7
        assert row["metrics"]["tokens"]["unit"] == "tokens"


def test_missing_runtime_is_blocked_with_null_reasons(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, runtime=["runtime-does-not-exist", "--"])

    report = run_benchmark(manifest)

    assert report["status"] == "unverified"
    assert all(run["status"] == "blocked" for run in report["runs"])
    assert all(
        run["metrics"]["ttft_ms"]["value"] is None
        and "runtime_unavailable" in run["metrics"]["ttft_ms"]["reason"]
        for run in report["runs"]
    )


def test_comparison_blocks_nulls_and_detects_stage_regression(tmp_path: Path) -> None:
    baseline = run_benchmark(_manifest(tmp_path))
    candidate = json.loads(json.dumps(baseline))
    candidate["aggregates"][0]["metrics"]["ttft_ms"]["value"] = 200.0

    result = compare_reports(baseline, candidate, tolerance=0.2)

    assert result["status"] == "blocked"
    assert any("ttft_ms" in path for path in result["regressions"])
    assert result["missing_metrics"] == []
