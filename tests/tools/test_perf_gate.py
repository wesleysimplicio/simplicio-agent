"""Tests for tools/perf_gate/ (issue #116): CI performance-regression gate.

Covers the pure comparison logic in compare.py with synthetic before/after
numbers (no real benchmark subprocess, no filesystem) plus the bootstrap-mode
behavior when no baseline is committed yet.
"""

import json

from tools.perf_gate.compare import (
    DEFAULT_THRESHOLD_PCT,
    compare_metrics,
    load_baseline,
)
from tools.perf_gate.runner import metric_key


class TestCompareMetrics:
    """Pure comparison logic — synthetic before/after numbers (AC1)."""

    def test_no_change_is_ok(self):
        baseline = {"scenario.a|variant": 100.0}
        current = {"scenario.a|variant": 100.0}
        diffs = compare_metrics(baseline, current, DEFAULT_THRESHOLD_PCT)
        assert len(diffs) == 1
        assert diffs[0].status == "ok"
        assert diffs[0].delta_pct == 0.0

    def test_small_regression_within_threshold_is_ok(self):
        baseline = {"scenario.a|variant": 100.0}
        current = {"scenario.a|variant": 110.0}  # +10%, under 20% threshold
        diffs = compare_metrics(baseline, current, 20.0)
        assert diffs[0].status == "ok"
        assert diffs[0].delta_pct == 10.0

    def test_regression_beyond_threshold_is_flagged(self):
        baseline = {"scenario.a|variant": 100.0}
        current = {"scenario.a|variant": 130.0}  # +30%, over 20% threshold
        diffs = compare_metrics(baseline, current, 20.0)
        assert diffs[0].status == "regression"
        assert diffs[0].delta_pct == 30.0

    def test_improvement_is_ok_not_regression(self):
        baseline = {"scenario.a|variant": 100.0}
        current = {"scenario.a|variant": 50.0}  # 2x faster
        diffs = compare_metrics(baseline, current, 20.0)
        assert diffs[0].status == "ok"
        assert diffs[0].delta_pct == -50.0

    def test_new_scenario_with_no_baseline_is_flagged_new_not_regression(self):
        baseline = {}
        current = {"scenario.new|variant": 42.0}
        diffs = compare_metrics(baseline, current, 20.0)
        assert diffs[0].status == "new"

    def test_missing_scenario_in_current_run_is_flagged_missing(self):
        baseline = {"scenario.gone|variant": 42.0}
        current = {}
        diffs = compare_metrics(baseline, current, 20.0)
        assert diffs[0].status == "missing"

    def test_zero_or_negative_baseline_is_flagged_new_not_division_error(self):
        baseline = {"scenario.a|variant": 0.0}
        current = {"scenario.a|variant": 5.0}
        diffs = compare_metrics(baseline, current, 20.0)
        assert diffs[0].status == "new"

    def test_multiple_scenarios_sorted_by_key(self):
        baseline = {"b|v": 10.0, "a|v": 10.0}
        current = {"b|v": 10.0, "a|v": 10.0}
        diffs = compare_metrics(baseline, current, 20.0)
        assert [d.key for d in diffs] == ["a|v", "b|v"]

    def test_exactly_at_threshold_boundary_is_not_a_regression(self):
        # compare_metrics uses strict > threshold, so exactly +20% at a 20%
        # threshold must NOT be flagged.
        baseline = {"scenario.a|variant": 100.0}
        current = {"scenario.a|variant": 120.0}
        diffs = compare_metrics(baseline, current, 20.0)
        assert diffs[0].status == "ok"


class TestLoadBaseline:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert load_baseline(tmp_path / "does-not-exist.json") == {}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert load_baseline(p) == {}

    def test_valid_baseline_loads(self, tmp_path):
        p = tmp_path / "baseline.json"
        doc = {"schema": "simplicio.perf-gate.baseline/v1", "metrics": {"a|v": 1.0}}
        p.write_text(json.dumps(doc), encoding="utf-8")
        loaded = load_baseline(p)
        assert loaded["metrics"] == {"a|v": 1.0}

    def test_bootstrap_mode_empty_metrics_map_is_valid(self):
        """The committed baseline_ci.json ships with an empty 'metrics' map
        (no real runner-measured baseline yet, per its own '_note') — compare.py
        must treat that as bootstrap mode (exit 0), not crash or fabricate data.
        """
        from tools.perf_gate.compare import DEFAULT_BASELINE

        doc = load_baseline(DEFAULT_BASELINE)
        assert doc.get("schema") == "simplicio.perf-gate.baseline/v1"
        assert doc.get("metrics") == {}, (
            "the committed baseline_ci.json should still be empty (bootstrap mode) "
            "until a real CI runner captures one via bootstrap_baseline.py"
        )


class TestMetricKey:
    def test_metric_key_format(self):
        assert metric_key("cli.cold_import", "sync") == "cli.cold_import|sync"
