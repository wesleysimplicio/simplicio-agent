#!/usr/bin/env python3
"""Slice D — Benchmark A/B collector for turn_latency= samples.

Reads the Simplicio gateway log and aggregates turn_latency= samples,
grouped by a label (e.g. "before" / "after" a speed change). Used to prove
a real end-to-end latency reduction after the velocity changes land.

Usage:
  python3 tools/bench_latency.py --log ~/.simplicio_agent/logs/gateway.log \
      --label after --out .simplicio/bench-after.jsonl
  python3 tools/bench_latency.py --compare .simplicio/bench-before.jsonl \
      .simplicio/bench-after.jsonl
"""
from __future__ import annotations
import argparse
import json
import re
import statistics
from pathlib import Path

# turn_latency=1234.5ms  (or s)  per-turn breakdown emitted by TurnLatencyProbe
SAMPLE_RE = re.compile(r"turn_latency=(\d+(?:\.\d+)?)(ms|s)")


def collect(log_path: str, label: str) -> list[dict]:
    samples = []
    p = Path(log_path)
    if not p.exists():
        return samples
    for line in p.read_text(errors="ignore").splitlines():
        m = SAMPLE_RE.search(line)
        if not m:
            continue
        val = float(m.group(1))
        if m.group(2) == "s":
            val *= 1000.0  # normalise to ms
        samples.append({"label": label, "ms": val, "raw": line.strip()[:200]})
    return samples


def summarize(samples: list[dict]) -> dict:
    if not samples:
        return {"count": 0}
    vals = [s["ms"] for s in samples]
    vals.sort()
    n = len(vals)
    p50 = statistics.median(vals)
    p95 = vals[min(n - 1, int(n * 0.95))]
    p99 = vals[min(n - 1, int(n * 0.99))]
    return {
        "count": n,
        "min_ms": round(vals[0], 1),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(p99, 1),
        "max_ms": round(vals[-1], 1),
        "mean_ms": round(statistics.mean(vals), 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--label", default="sample")
    ap.add_argument("--out", help="write collected samples as JSONL")
    ap.add_argument("--compare", nargs="*", default=[],
                    help="compare two JSONL files (before, after)")
    args = ap.parse_args()

    if args.compare:
        for f in args.compare:
            samples = [json.loads(l) for l in Path(f).read_text().splitlines() if l.strip()]
            print(f"{f}: {json.dumps(summarize(samples))}")
        return

    samples = collect(args.log, args.label)
    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(s) for s in samples))
    print(json.dumps(summarize(samples)))


if __name__ == "__main__":
    main()
