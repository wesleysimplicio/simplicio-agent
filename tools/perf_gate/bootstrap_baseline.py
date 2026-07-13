#!/usr/bin/env python3
"""Capture the current runner's benchmark numbers into baseline_ci.json.

Deliberate, human-invoked action -- NOT part of the gate's own path
(``compare.py`` never calls this). Updating the CI baseline is a reviewable
diff committed in the same PR that intentionally changed performance (see
docs/performance.md), never an automatic side effect of a CI run. Mirrors
``tools/rename_guard/bootstrap_baseline.py``.

Usage:
    python3 -m tools.perf_gate.bootstrap_baseline
    python3 -m tools.perf_gate.bootstrap_baseline --runs 5 --threshold-pct 25
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.perf_gate.runner import (
    DEFAULT_ITERATIONS,
    DEFAULT_RUNS,
    collect_metrics,
    runner_hw_annotation,
)

GATE_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = GATE_DIR / "baseline_ci.json"
DEFAULT_THRESHOLD_PCT = 20.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--threshold-pct", type=float, default=DEFAULT_THRESHOLD_PCT)
    args = parser.parse_args(argv)

    metrics = collect_metrics(runs=args.runs, iterations=args.iterations)
    if not metrics:
        print("ERROR: benchmark produced no usable metrics -- refusing to write an empty baseline.")
        return 1

    doc = {
        "schema": "simplicio.perf-gate.baseline/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runner": runner_hw_annotation(),
        "threshold_pct": args.threshold_pct,
        "samples_per_scenario": args.runs,
        "iterations": args.iterations,
        "metrics": dict(sorted(metrics.items())),
    }
    args.out.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"baseline written: {args.out} ({len(metrics)} scenario/variant pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
