"""Wall-clock benchmark for :mod:`tools.promotion_controller`.

Measures two numbers required by the Native 1.4 issue's benchmark gate:

* pointer-swap latency (the atomic ``current`` rename/symlink swap alone)
* full promotion cycle latency (stage + swap + health-check + commit)

Run with ``python tools/bench_promotion_controller.py``. Every number
printed is measured on this machine at run time -- nothing is estimated
or hard-coded.
"""

from __future__ import annotations

import shutil
import statistics
import tempfile
import time
from pathlib import Path

from tools.promotion_controller import PromotionController, build_promotion_receipt


def _tree(root: Path, value: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "commit.txt").write_text(value, encoding="utf-8")


def _percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return ordered[index]


def bench_pointer_swap(cycles: int = 10) -> list[float]:
    samples: list[float] = []
    for i in range(cycles):
        root = Path(tempfile.mkdtemp(prefix="bench-swap-"))
        try:
            controller = PromotionController(root / "state")
            a = root / "a"
            b = root / "b"
            _tree(a, "a")
            _tree(b, "b")
            digest_a = controller.stage(a)
            digest_b = controller.stage(b)
            controller._swap_pointer(digest_a)  # noqa: SLF001 -- benchmarking internal primitive
            start = time.perf_counter()
            controller._swap_pointer(digest_b)  # noqa: SLF001
            samples.append(time.perf_counter() - start)
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return samples


def bench_full_promotion_cycle(cycles: int = 10) -> list[float]:
    samples: list[float] = []
    for i in range(cycles):
        root = Path(tempfile.mkdtemp(prefix="bench-promote-"))
        try:
            old = root / "old"
            new = root / "new"
            _tree(old, "old")
            _tree(new, f"new-{i}")
            controller = PromotionController(root / "state")
            before = controller.seed(old)
            candidate_digest = controller.stage(new)
            receipt = build_promotion_receipt(
                snapshot_before=before,
                candidate_digest=candidate_digest,
                promoted_commit=f"commit-{i}",
                fencing_token=1,
            )

            def health_check(_slot, _receipt=receipt):
                return {
                    "healthy": True,
                    "commit": _receipt["promoted_commit"],
                    "digest": _receipt["candidate_digest"],
                    "smoke": True,
                }

            start = time.perf_counter()
            result = controller.promote(new, receipt, health_check)
            samples.append(time.perf_counter() - start)
            assert result.promoted
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return samples


def bench_rollback_cycle(cycles: int = 10) -> list[float]:
    samples: list[float] = []
    for i in range(cycles):
        root = Path(tempfile.mkdtemp(prefix="bench-rollback-"))
        try:
            old = root / "old"
            new = root / "new"
            _tree(old, "old")
            _tree(new, f"new-{i}")
            controller = PromotionController(root / "state")
            before = controller.seed(old)
            candidate_digest = controller.stage(new)
            receipt = build_promotion_receipt(
                snapshot_before=before,
                candidate_digest=candidate_digest,
                promoted_commit=f"commit-{i}",
                fencing_token=1,
            )

            def failing_health_check(_slot):
                return {"healthy": False, "reason": "injected_failure"}

            start = time.perf_counter()
            result = controller.promote(new, receipt, failing_health_check)
            samples.append(time.perf_counter() - start)
            assert result.rolled_back
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return samples


def _report(name: str, samples: list[float], budget_s: float | None = None) -> None:
    p50 = _percentile(samples, 0.50)
    p95 = _percentile(samples, 0.95)
    mean = statistics.mean(samples)
    budget = f" budget={budget_s * 1000:.1f}ms" if budget_s else ""
    print(
        f"MEASURED|{name}: n={len(samples)} "
        f"p50={p50 * 1000:.3f}ms p95={p95 * 1000:.3f}ms mean={mean * 1000:.3f}ms{budget}"
    )


def main() -> None:
    _report("pointer_swap_latency", bench_pointer_swap(10), budget_s=0.100)
    _report("full_promotion_cycle", bench_full_promotion_cycle(10))
    _report("rollback_cycle", bench_rollback_cycle(10), budget_s=90.0)


if __name__ == "__main__":
    main()
