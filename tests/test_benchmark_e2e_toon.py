"""Smoke test for the `toon` scenario in scripts/benchmark_e2e.py (issue #16).

Not a numbers-regression test (timing is inherently noisy) -- just proves
the scenario is wired into SCENARIOS, runs without error, and reports a
token-count delta for each payload shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.benchmark_e2e import SCENARIOS, Report, bench_toon


def test_toon_scenario_registered():
    assert "toon" in SCENARIOS
    assert SCENARIOS["toon"] is bench_toon


def test_bench_toon_runs_and_reports_token_counts():
    report = Report()
    bench_toon(report, iterations=5)

    scenarios = {r.scenario for r in report.results}
    assert "toon.encode[uniform_array_20_users]" in scenarios
    assert "toon.encode[tool_result_files_modified]" in scenarios
    assert "toon.encode[context_engine_error]" in scenarios

    for r in report.results:
        assert "tokens:" in r.notes
        assert r.ops == 5
        assert r.total_s >= 0


def test_bench_toon_current_variant_reports_savings_for_uniform_array():
    report = Report()
    bench_toon(report, iterations=1)

    current = next(
        r for r in report.results
        if r.scenario == "toon.encode[uniform_array_20_users]" and r.variant.startswith("current")
    )
    assert "json -> " in current.notes
    assert "saved)" in current.notes
