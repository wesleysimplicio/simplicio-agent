#!/usr/bin/env python3
"""Small offline benchmark for the #462 async runtime boundary.

This measures scheduler overhead and bounded I/O concurrency only. It is not a
claim about provider latency or LLM token savings; production claims require a
Runtime/Mapper/Loop receipt with the provider usage counters attached.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.runtime_context import AgentRuntimeContext


async def _sleep_work(delay_s: float) -> None:
    await asyncio.sleep(delay_s)


async def _run_serial(samples: int, delay_s: float) -> float:
    started = time.perf_counter()
    for _ in range(samples):
        await _sleep_work(delay_s)
    return time.perf_counter() - started


async def _run_bounded(samples: int, delay_s: float, workers: int) -> tuple[float, dict]:
    started = time.perf_counter()
    async with AgentRuntimeContext(max_workers=workers, max_pending=samples) as runtime:
        await asyncio.gather(
            *(runtime.run(lambda: _sleep_work(delay_s), task_id=f"bench-{i}") for i in range(samples))
        )
        metrics = runtime.snapshot()["metrics"]
    return time.perf_counter() - started, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--delay-ms", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.samples < 1 or args.workers < 1 or args.delay_ms < 0:
        parser.error("samples, workers and delay must be non-negative/positive")

    delay_s = args.delay_ms / 1000
    serial_s = asyncio.run(_run_serial(args.samples, delay_s))
    bounded_s, metrics = asyncio.run(_run_bounded(args.samples, delay_s, args.workers))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "schema": "simplicio-agent/async-runtime-benchmark/v1",
        "kind": "synthetic_io_scheduler",
        "samples": args.samples,
        "delay_ms": args.delay_ms,
        "workers": args.workers,
        "serial_wall_s": round(serial_s, 6),
        "bounded_wall_s": round(bounded_s, 6),
        "speedup": round(serial_s / bounded_s, 3) if bounded_s else 0.0,
        "cpu_user_s": round(usage.ru_utime, 6),
        "cpu_system_s": round(usage.ru_stime, 6),
        "max_rss_kb": usage.ru_maxrss,
        "runtime_metrics": metrics,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
