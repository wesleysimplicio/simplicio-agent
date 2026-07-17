"""Run the stub-provider baseline repeatedly and check cross-run variance.

This is a real, executable stability check (not a fabricated claim): it runs
``run_benchmark`` N times against the same fixture manifest and asserts that
each category-level metric varies by no more than ``--max-variance-pct``
across the runs, using ``(max - min) / mean`` as the variance measure.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from bench.harness import DEFAULT_FIXTURES, run_benchmark

METRICS = ("input_tokens", "output_tokens", "latency_us.p50", "latency_us.p95")


def _get(row: dict[str, Any], metric: str) -> float:
    if "." not in metric:
        return float(row[metric])
    value: Any = row
    for part in metric.split("."):
        value = value[part]
    return float(value)


def _variance_pct(values: list[float]) -> float:
    mean = statistics.fmean(values)
    if mean == 0:
        return 0.0 if max(values) == 0 else float("inf")
    return (max(values) - min(values)) / mean * 100.0


def check_stability(
    fixtures: Path = DEFAULT_FIXTURES,
    *,
    runs: int = 3,
    repeats: int = 100,
    warmup: int = 5,
    max_variance_pct: float = 5.0,
) -> dict[str, Any]:
    """Run the baseline ``runs`` times and report per-metric variance."""

    reports = [
        run_benchmark(fixtures, provider="stub", repeats=repeats, warmup=warmup)
        for _ in range(runs)
    ]
    category_ids = [row["id"] for row in reports[0]["categories"]]
    rows: dict[str, dict[str, dict[str, Any]]] = {}
    violations: list[str] = []
    for category_id in category_ids:
        rows[category_id] = {}
        for metric in METRICS:
            values = []
            for report in reports:
                row = next(r for r in report["categories"] if r["id"] == category_id)
                values.append(_get(row, metric))
            variance_pct = _variance_pct(values)
            rows[category_id][metric] = {
                "values": values,
                "variance_pct": variance_pct,
            }
            if variance_pct > max_variance_pct:
                violations.append(f"{category_id}.{metric}={variance_pct:.2f}%")
    return {
        "schema": "simplicio.bench-stability/v1",
        "runs": runs,
        "repeats": repeats,
        "warmup": warmup,
        "max_variance_pct": max_variance_pct,
        "status": "pass" if not violations else "fail",
        "violations": violations,
        "categories": rows,
        "evidence": f"MEASURED|{runs} consecutive stub-provider baseline runs compared for variance",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--max-variance-pct", type=float, default=5.0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    result = check_stability(
        args.fixtures,
        runs=args.runs,
        repeats=args.repeats,
        warmup=args.warmup,
        max_variance_pct=args.max_variance_pct,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
