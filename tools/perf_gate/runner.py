#!/usr/bin/env python3
"""Collect performance metrics via ``scripts/benchmark_e2e.py --json``.

Scope note (issue #116): the gate covers ``scripts/benchmark_e2e.py`` only.
The issue also mentions the ``scripts/turbo-speed/`` scenarios, but those
scripts interleave a human-readable table with their ``--json`` payload on
stdout (JSON is appended *after* the table, not exclusive to it) and probe
things like an installed ``hermes``/``simplicio-agent`` binary on PATH and
subprocess TTFP, which are not reliably comparable across CI runner
invocations. ``benchmark_e2e.py`` is the one script in this repo that is
already "offline, CI-ready" (its own module docstring) and emits *only*
JSON with ``--json`` -- so it is the one wired into the gate here. Adding
turbo-speed scenarios is a follow-up (needs a small, separate change to
those scripts' own ``--json`` handling first) and is out of scope for this
change.

This module runs the benchmark script multiple times (subprocess per run,
so each run pays its own warmup/GC noise) and takes the **median**
``per_op_us`` per (scenario, variant) key -- reducing run-to-run noise
without hiding a real regression.
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARK_SCRIPT = REPO_ROOT / "scripts" / "benchmark_e2e.py"

DEFAULT_RUNS = 3
DEFAULT_ITERATIONS = 1500


def metric_key(scenario: str, variant: str) -> str:
    return f"{scenario}|{variant}"


def _run_once(iterations: int, skip: list[str] | None = None) -> list[dict[str, Any]]:
    cmd = [sys.executable, str(BENCHMARK_SCRIPT), "--json", "--iterations", str(iterations)]
    for s in skip or []:
        cmd += ["--skip", s]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"benchmark_e2e.py exited {proc.returncode}\nstdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}"
        )
    return json.loads(proc.stdout)


def collect_metrics(
    runs: int = DEFAULT_RUNS,
    iterations: int = DEFAULT_ITERATIONS,
    skip: list[str] | None = None,
) -> dict[str, float]:
    """Run the benchmark ``runs`` times and return the median ``per_op_us``
    per (scenario, variant) key.

    Rows with ``ops == 0`` (e.g. the ``cli.cold_import`` "FAILED" row when
    the subprocess import itself fails in a broken env) are excluded --
    they have no meaningful ``per_op_us`` and would poison the median.
    """
    samples: dict[str, list[float]] = {}
    for _ in range(max(1, runs)):
        rows = _run_once(iterations, skip=skip)
        for row in rows:
            if not row.get("ops"):
                continue
            per_op_us = row.get("per_op_us")
            if per_op_us is None or per_op_us != per_op_us:  # NaN guard
                continue
            key = metric_key(row["scenario"], row["variant"])
            samples.setdefault(key, []).append(float(per_op_us))

    return {key: statistics.median(values) for key, values in samples.items() if values}


def runner_hw_annotation() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
    }
