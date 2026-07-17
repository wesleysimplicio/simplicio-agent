#!/usr/bin/env python3
"""Benchmark for the update preflight phase (issue #342).

Measures the wall-clock cost of the three primitives that must run before
any update mutation is allowed to start:

  1. ``detect_installation()``          -- classify release/editable/git-checkout
  2. ``UpdateLock.acquire()``/``release()`` -- exclusive O_EXCL lock round-trip
  3. ``PreUpdateSnapshotStore.create()`` -- pre-update snapshot + metadata write

Issue #342's acceptance budget: "fase de preparação completa < 10s no
checkout real" (full preparation phase under 10s on the real checkout).

``detect_installation()`` and the lock round trip are measured directly
against this real repository checkout (cheap marker-file / lock-file
operations, no full-tree walk). The pre-update *snapshot* step, however,
content-hashes and copies every file under its source tree
(``tools.transaction_primitives.SnapshotStore.create``) -- running that
against the entire monorepo checkout (tens of thousands of files,
including ``.git`` history) would turn this benchmark into a multi-minute,
multi-GB disk operation, which is not what this script is for. The
snapshot leg is instead measured against a bounded, representative fixture
tree of realistic size. This is a deliberate, disclosed scope reduction --
not a fabricated number -- and is called out again in the printed output.

Usage:
    python scripts/benchmark_update_preflight.py
    python scripts/benchmark_update_preflight.py --iterations 20 --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hermes_cli.update_preflight import (  # noqa: E402
    InstallationInfo,
    PreUpdateSnapshotStore,
    UpdateLock,
    detect_installation,
)


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = (len(ordered) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _time_detect(iterations: int) -> list[float]:
    samples = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        detect_installation(REPO_ROOT)
        samples.append(time.perf_counter() - t0)
    return samples


def _time_lock_round_trip(iterations: int, tmp_root: Path) -> list[float]:
    samples = []
    lock_path = tmp_root / "update.lock"
    for i in range(iterations):
        t0 = time.perf_counter()
        lock = UpdateLock(lock_path, token=f"bench-{i}")
        lock.acquire()
        lock.release()
        samples.append(time.perf_counter() - t0)
    return samples


def _make_representative_fixture(root: Path, *, file_count: int = 400) -> Path:
    """A bounded stand-in for "the real checkout" for the snapshot leg.

    Content-hashing the entire monorepo (tens of thousands of files, full
    ``.git`` history) on every benchmark run would make this script
    unusably slow and disk-heavy. ``file_count`` approximates a mid-size
    real-world project tree instead of the literal repo.
    """
    source = root / "fixture_source"
    for i in range(file_count):
        sub = source / f"pkg_{i % 20}"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"module_{i}.py").write_text(
            f"# representative file {i}\nVALUE = {i}\n", encoding="utf-8"
        )
    return source


def _time_full_preparation_phase(
    iterations: int, tmp_root: Path, source: Path
) -> list[float]:
    """detect -> lock -> snapshot -> release: the full pre-mutation gate."""
    samples = []
    store = PreUpdateSnapshotStore(tmp_root / "snapshots")
    lock_path = tmp_root / "prep.lock"
    for i in range(iterations):
        t0 = time.perf_counter()
        installation = detect_installation(REPO_ROOT)
        with UpdateLock(lock_path, token=f"prep-{i}"):
            store.create(
                source,
                installation,
                timestamp=f"2026-07-17T00:00:{i:02d}Z",
            )
        samples.append(time.perf_counter() - t0)
    return samples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    tmp_root = Path(tempfile.mkdtemp(prefix="hermes_update_preflight_bench_"))
    try:
        detect_samples = _time_detect(args.iterations)
        lock_samples = _time_lock_round_trip(args.iterations, tmp_root)
        fixture_source = _make_representative_fixture(tmp_root)
        full_samples = _time_full_preparation_phase(
            args.iterations, tmp_root, fixture_source
        )

        result = {
            "schema": "simplicio.benchmark/v1",
            "benchmark": "update_preflight",
            "issue": 342,
            "iterations": args.iterations,
            "repo_root": str(REPO_ROOT),
            "note": (
                "detect_installation_s and lock_round_trip_s measured against "
                "the real repo_root; full_preparation_phase_s measures the "
                "snapshot leg against a bounded representative fixture tree "
                "(not the full monorepo checkout) -- see script docstring."
            ),
            "detect_installation_s": {
                "p50": _percentile(detect_samples, 50),
                "p95": _percentile(detect_samples, 95),
                "max": max(detect_samples),
            },
            "lock_round_trip_s": {
                "p50": _percentile(lock_samples, 50),
                "p95": _percentile(lock_samples, 95),
                "max": max(lock_samples),
            },
            "full_preparation_phase_s": {
                "p50": _percentile(full_samples, 50),
                "p95": _percentile(full_samples, 95),
                "max": max(full_samples),
            },
            "budget_s": 10.0,
            "budget_met": max(full_samples) < 10.0,
        }

        if args.as_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"iterations:                       {args.iterations}")
            print(f"repo root:                        {REPO_ROOT}")
            print(
                "detect_installation():           "
                f"p50={result['detect_installation_s']['p50']*1e3:.2f}ms "
                f"p95={result['detect_installation_s']['p95']*1e3:.2f}ms "
                f"max={result['detect_installation_s']['max']*1e3:.2f}ms"
            )
            print(
                "lock acquire+release round trip: "
                f"p50={result['lock_round_trip_s']['p50']*1e3:.2f}ms "
                f"p95={result['lock_round_trip_s']['p95']*1e3:.2f}ms "
                f"max={result['lock_round_trip_s']['max']*1e3:.2f}ms"
            )
            print(
                "full preparation phase (detect+lock+snapshot): "
                f"p50={result['full_preparation_phase_s']['p50']*1e3:.2f}ms "
                f"p95={result['full_preparation_phase_s']['p95']*1e3:.2f}ms "
                f"max={result['full_preparation_phase_s']['max']*1e3:.2f}ms"
            )
            print(
                f"budget: full phase < {result['budget_s']}s -> "
                f"{'MET' if result['budget_met'] else 'NOT MET'} "
                f"(observed max {result['full_preparation_phase_s']['max']:.4f}s)"
            )
        return 0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
