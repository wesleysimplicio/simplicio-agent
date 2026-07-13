#!/usr/bin/env python3
"""Compare current benchmark metrics against the committed CI baseline.

Usage:
    python3 -m tools.perf_gate.compare                  # runs the real benchmark, gates
    python3 -m tools.perf_gate.compare --json out.json  # also writes a machine-readable report

Exit codes:
    0 -- no regression beyond threshold (or no baseline committed yet: see
         "bootstrap mode" below)
    1 -- at least one scenario regressed beyond ``threshold_pct``

Never writes ``baseline_ci.json`` itself -- bumping the baseline is a
reviewable, human-invoked action via ``tools/perf_gate/bootstrap_baseline.py``
(same discipline as ``tools/rename_guard/``), never automatic.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tools.perf_gate.runner import (
    DEFAULT_ITERATIONS,
    DEFAULT_RUNS,
    collect_metrics,
    runner_hw_annotation,
)

GATE_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = GATE_DIR / "baseline_ci.json"
DEFAULT_THRESHOLD_PCT = 20.0


@dataclass
class ScenarioDiff:
    key: str
    baseline_us: float
    current_us: float
    delta_pct: float
    status: str  # "ok" | "regression" | "new" (no baseline) | "missing" (no current)


def load_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def compare_metrics(
    baseline_metrics: dict[str, float],
    current_metrics: dict[str, float],
    threshold_pct: float,
) -> list[ScenarioDiff]:
    """Pure comparison function -- no subprocess, no filesystem. This is the
    piece unit-tested with synthetic before/after numbers (issue #116 AC1).
    """
    diffs: list[ScenarioDiff] = []
    all_keys = sorted(set(baseline_metrics) | set(current_metrics))
    for key in all_keys:
        base = baseline_metrics.get(key)
        curr = current_metrics.get(key)
        if base is None:
            diffs.append(ScenarioDiff(key, float("nan"), curr, 0.0, "new"))
            continue
        if curr is None:
            diffs.append(ScenarioDiff(key, base, float("nan"), 0.0, "missing"))
            continue
        if base <= 0:
            # Can't compute a meaningful percentage against a zero/negative
            # baseline; flag as new rather than dividing by zero.
            diffs.append(ScenarioDiff(key, base, curr, 0.0, "new"))
            continue
        delta_pct = (curr - base) / base * 100.0
        status = "regression" if delta_pct > threshold_pct else "ok"
        diffs.append(ScenarioDiff(key, base, curr, delta_pct, status))
    return diffs


def print_report(diffs: list[ScenarioDiff], threshold_pct: float) -> None:
    headers = ("SCENARIO | VARIANT", "BASELINE (us)", "CURRENT (us)", "DELTA %", "STATUS")
    widths = [50, 14, 14, 10, 10]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(f"Perf gate report (threshold: +{threshold_pct}%)")
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for d in diffs:
        base_s = "n/a" if d.baseline_us != d.baseline_us else f"{d.baseline_us:.3f}"
        curr_s = "n/a" if d.current_us != d.current_us else f"{d.current_us:.3f}"
        delta_s = "n/a" if d.status in ("new", "missing") else f"{d.delta_pct:+.1f}%"
        print(fmt.format(d.key[:50], base_s, curr_s, delta_s, d.status.upper()))
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--threshold-pct", type=float, default=None, help="override the baseline's committed threshold")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="benchmark repetitions to take the median over (default: %(default)s)")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS, help="--iterations passed to benchmark_e2e.py (default: %(default)s)")
    parser.add_argument("--json", type=Path, default=None, help="also write a machine-readable report to this path")
    args = parser.parse_args(argv)

    baseline_doc = load_baseline(args.baseline)
    baseline_metrics: dict[str, float] = baseline_doc.get("metrics", {})

    if not baseline_metrics:
        print(
            f"No CI baseline committed yet at {args.baseline} (or it has no 'metrics').\n"
            "This is expected for the first run of this gate on a given runner class.\n"
            "Bootstrap it explicitly and commit the result in a reviewable PR:\n"
            "    python3 -m tools.perf_gate.bootstrap_baseline\n"
            "Skipping the regression check for now (bootstrap mode, exit 0)."
        )
        return 0

    threshold_pct = args.threshold_pct if args.threshold_pct is not None else baseline_doc.get("threshold_pct", DEFAULT_THRESHOLD_PCT)

    current_metrics = collect_metrics(runs=args.runs, iterations=args.iterations)
    diffs = compare_metrics(baseline_metrics, current_metrics, threshold_pct)
    print_report(diffs, threshold_pct)

    regressions = [d for d in diffs if d.status == "regression"]
    missing = [d for d in diffs if d.status == "missing"]
    if missing:
        print(f"Note: {len(missing)} baseline scenario(s) did not appear in this run (renamed/skipped?): "
              + ", ".join(d.key for d in missing))

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "schema": "simplicio.perf-gate.report/v1",
                    "threshold_pct": threshold_pct,
                    "runner": runner_hw_annotation(),
                    "diffs": [asdict(d) for d in diffs],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if regressions:
        print(f"FAIL: {len(regressions)} scenario(s) regressed beyond +{threshold_pct}%:")
        for d in regressions:
            print(f"  - {d.key}: {d.baseline_us:.3f}us -> {d.current_us:.3f}us ({d.delta_pct:+.1f}%)")
        return 1

    print(f"OK: no scenario regressed beyond +{threshold_pct}%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
