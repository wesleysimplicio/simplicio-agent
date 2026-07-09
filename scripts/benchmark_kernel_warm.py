#!/usr/bin/env python3
"""Warm vs. cold kernel_binding benchmark (#109 / simplicio-runtime#2983).

Measures the actual latency win of routing `gate classify` through a
persistent `simplicio serve --mcp --stdio` connection (warm mode) instead
of a fresh `subprocess.run(["simplicio", "gate", "classify", ...])` per
call (the classic path, still the default -- warm mode is opt-in via
SIMPLICIO_AGENT_KERNEL_WARM=1).

Requires a `simplicio` binary on PATH (or HERMES_KERNEL_BIN) built with the
in-process `simplicio_gate` MCP tool fast path (simplicio-runtime#2983) --
without it, warm mode still eliminates the Python-side subprocess.run, but
the server self-execs a fresh process per call same as today, so the
speedup will be much smaller (client-side savings only).

Usage:
    python scripts/benchmark_kernel_warm.py
    python scripts/benchmark_kernel_warm.py --iterations 50 --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tools.kernel_binding as kb  # noqa: E402


def _time_calls(action: str, iterations: int) -> list[float]:
    samples = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        try:
            kb._run_kernel(["gate", "classify", "--action", action, "--json"], timeout=8.0)
        except kb.KernelBindingError as exc:
            print(f"warning: kernel call failed: {exc}", file=sys.stderr)
            continue
        samples.append(time.perf_counter() - t0)
    return samples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--action", default="show status")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    if not kb.is_kernel_available():
        print("error: no simplicio kernel binary on PATH (HERMES_KERNEL_BIN)", file=sys.stderr)
        return 2

    # Cold: classic subprocess.run path, warm mode off.
    kb.reset_warm_client()
    import os
    os.environ.pop(kb._WARM_MODE_ENV, None)
    cold = _time_calls(args.action, args.iterations)

    # Warm: persistent connection, first call pays the spawn+handshake.
    os.environ[kb._WARM_MODE_ENV] = "1"
    kb.reset_warm_client()
    warm_all = _time_calls(args.action, args.iterations)
    kb.reset_warm_client()
    os.environ.pop(kb._WARM_MODE_ENV, None)

    warm_first = warm_all[0] if warm_all else None
    warm_steady = warm_all[1:] if len(warm_all) > 1 else warm_all

    def _median(xs: list[float]) -> float | None:
        return statistics.median(xs) if xs else None

    result = {
        "iterations": args.iterations,
        "cold_median_s": _median(cold),
        "warm_first_call_s": warm_first,
        "warm_steady_median_s": _median(warm_steady),
        "speedup_steady_vs_cold": (
            _median(cold) / _median(warm_steady)
            if _median(cold) and _median(warm_steady)
            else None
        ),
    }

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"iterations:            {args.iterations}")
        print(f"cold (subprocess.run): {result['cold_median_s']*1e3:.2f} ms/call (median)")
        if warm_first is not None:
            print(f"warm, first call:       {warm_first*1e3:.2f} ms (pays spawn+handshake)")
        if result["warm_steady_median_s"] is not None:
            print(
                f"warm, steady state:    {result['warm_steady_median_s']*1e3:.2f} ms/call (median)"
            )
        if result["speedup_steady_vs_cold"] is not None:
            print(f"speedup (steady):      {result['speedup_steady_vs_cold']:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
