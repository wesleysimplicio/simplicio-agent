#!/usr/bin/env python3
"""Performance benchmark for issue #339: EffectInterceptor overhead.

Measures the wall-clock overhead of routing fs_write and fs_read operations
through :class:`tools.shadow_effects.EffectInterceptor` (typed request,
overlay staging / read-through callback, decision object) versus performing
the same operation directly against the filesystem with no interception.

The issue's acceptance budget is: shadow overhead <= 2x direct execution time
per fixture category. This script reports MEASURED medians (and p95) over N
iterations for both categories; it does not fabricate or estimate numbers.

Usage:
    python -m scripts.bench_shadow_effects [--iterations N]
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from pathlib import Path

from tools.shadow_effects import EffectInterceptor, EffectKind, EffectRequest, ShadowOverlay


def _percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return ordered[index]


def bench_fs_write(iterations: int, root: Path) -> tuple[list[float], list[float]]:
    direct_dir = root / "direct_write"
    direct_dir.mkdir(parents=True, exist_ok=True)
    direct_times: list[float] = []
    for i in range(iterations):
        target = direct_dir / f"file_{i}.txt"
        start = time.perf_counter()
        target.write_text("payload-content", encoding="utf-8")
        direct_times.append(time.perf_counter() - start)

    overlay_dir = root / "overlay_write"
    overlay = ShadowOverlay(overlay_dir)
    interceptor = EffectInterceptor(overlay=overlay)
    shadow_times: list[float] = []
    for i in range(iterations):
        request = EffectRequest(
            EffectKind.FS_WRITE,
            "write",
            payload={"path": f"file_{i}.txt", "content": "payload-content"},
        )
        start = time.perf_counter()
        interceptor.intercept(request)
        shadow_times.append(time.perf_counter() - start)

    return direct_times, shadow_times


def bench_fs_read(iterations: int, root: Path) -> tuple[list[float], list[float]]:
    read_dir = root / "read_source"
    read_dir.mkdir(parents=True, exist_ok=True)
    target = read_dir / "source.txt"
    target.write_text("payload-content" * 8, encoding="utf-8")

    direct_times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        target.read_text(encoding="utf-8")
        direct_times.append(time.perf_counter() - start)

    interceptor = EffectInterceptor()

    def read_through(req: EffectRequest) -> str:
        return (read_dir / req.target).read_text(encoding="utf-8")

    shadow_times: list[float] = []
    for _ in range(iterations):
        request = EffectRequest(EffectKind.FS_READ, "read", "source.txt")
        start = time.perf_counter()
        interceptor.intercept(request, read_through=read_through)
        shadow_times.append(time.perf_counter() - start)

    return direct_times, shadow_times


def _report(name: str, direct: list[float], shadow: list[float]) -> None:
    direct_median = statistics.median(direct)
    shadow_median = statistics.median(shadow)
    direct_p95 = _percentile(direct, 0.95)
    shadow_p95 = _percentile(shadow, 0.95)
    ratio_median = shadow_median / direct_median if direct_median else float("inf")
    ratio_p95 = shadow_p95 / direct_p95 if direct_p95 else float("inf")
    budget_ok = ratio_median <= 2.0
    print(f"=== {name} (N={len(direct)}) ===")
    print(f"  direct  median={direct_median * 1e6:.2f}us  p95={direct_p95 * 1e6:.2f}us")
    print(f"  shadow  median={shadow_median * 1e6:.2f}us  p95={shadow_p95 * 1e6:.2f}us")
    print(f"  overhead ratio  median={ratio_median:.2f}x  p95={ratio_p95:.2f}x")
    print(f"  MEASURED| budget<=2x: {'PASS' if budget_ok else 'FAIL'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=500)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="shadow-bench-") as tmp:
        root = Path(tmp)
        write_direct, write_shadow = bench_fs_write(args.iterations, root)
        read_direct, read_shadow = bench_fs_read(args.iterations, root)

    _report("fs_write", write_direct, write_shadow)
    _report("fs_read", read_direct, read_shadow)


if __name__ == "__main__":
    main()
