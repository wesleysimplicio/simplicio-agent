#!/usr/bin/env python3
"""Performance benchmark for issue #338: snapshot create/restore latency.

Measures MEASURED wall-clock latency of ``SnapshotStore.create`` and
``SnapshotStore.restore`` over a representative directory (by default, a
real subtree of this checkout: ``tools/``), plus the per-mutation overhead
of ``TransactionJournal.append``. Reports p50/p95 over N runs; nothing here
is fabricated or estimated.

Issue #338's stated budget: create < 5s, restore < 10s, journal append
overhead per mutation < 5ms.

Usage:
    python -m scripts.bench_transaction_primitives [--runs N] [--source PATH]
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from tools.transaction_primitives import SnapshotStore, TransactionJournal


def _percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return ordered[index]


def _report(name: str, samples: list[float], budget_seconds: float | None) -> bool:
    median = statistics.median(samples)
    p95 = _percentile(samples, 0.95)
    ok = budget_seconds is None or p95 <= budget_seconds
    budget_text = f"budget<={budget_seconds}s" if budget_seconds is not None else "no budget"
    print(f"=== {name} (N={len(samples)}) ===")
    print(f"  MEASURED| p50={median * 1000:.2f}ms  p95={p95 * 1000:.2f}ms  {budget_text}: {'PASS' if ok else 'FAIL'}")
    return ok


def bench_create(source: Path, runs: int) -> list[float]:
    samples = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory(prefix="snapshot-store-") as store_dir:
            store = SnapshotStore(Path(store_dir))
            start = time.perf_counter()
            store.create(source)
            samples.append(time.perf_counter() - start)
    return samples


def bench_restore(source: Path, runs: int) -> list[float]:
    samples = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory(prefix="snapshot-store-") as store_dir:
            store = SnapshotStore(Path(store_dir))
            manifest = store.create(source)
            with tempfile.TemporaryDirectory(prefix="snapshot-restore-parent-") as parent:
                target = Path(parent) / "restored"
                start = time.perf_counter()
                store.restore(manifest, target)
                samples.append(time.perf_counter() - start)
    return samples


def bench_journal_append(runs: int) -> list[float]:
    samples = []
    with tempfile.TemporaryDirectory(prefix="journal-bench-") as tmp:
        journal = TransactionJournal(Path(tmp) / "journal.jsonl")
        for i in range(runs):
            start = time.perf_counter()
            journal.append("mutation", {"n": i})
            samples.append(time.perf_counter() - start)
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "tools",
        help="Directory snapshotted for create/restore benchmarks (default: tools/).",
    )
    args = parser.parse_args()

    original_source = args.source.resolve()
    with tempfile.TemporaryDirectory(prefix="snapshot-bench-source-") as frozen_dir:
        # Freeze a static copy: benchmarking a live source tree risks it being
        # mutated mid-run (e.g. the interpreter writing __pycache__/*.pyc into
        # the very directory being snapshotted), which is an environment
        # artifact rather than a library defect.
        source = Path(frozen_dir) / "source"
        shutil.copytree(
            original_source,
            source,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        file_count = sum(1 for p in source.rglob("*") if p.is_file())
        total_bytes = sum(p.stat().st_size for p in source.rglob("*") if p.is_file())
        print(f"source={original_source} (frozen copy) files={file_count} bytes={total_bytes}")

        create_samples = bench_create(source, args.runs)
        restore_samples = bench_restore(source, args.runs)
    append_samples = bench_journal_append(max(args.runs, 50))

    ok_create = _report("snapshot create", create_samples, budget_seconds=5.0)
    ok_restore = _report("snapshot restore", restore_samples, budget_seconds=10.0)
    ok_append = _report("journal append", append_samples, budget_seconds=0.005)

    if not (ok_create and ok_restore and ok_append):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
