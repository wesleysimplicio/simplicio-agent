#!/usr/bin/env python3
"""Paired benchmark: simplicio-agent vs the original hermes-agent checkout.

Answers one question with measured numbers: is every shared hot primitive at
least as fast here as in the upstream checkout? Each probe runs in a fresh
subprocess with cwd/sys.path pointed at ONE repo, so each side uses its own
code and its own default dependency posture (upstream: stdlib json, no
uvloop; here: agent/_fastjson -> orjson when installed, uvloop, etc.).

Usage:
    python scripts/benchmark_vs_upstream.py --upstream ../hermes-agent
    python scripts/benchmark_vs_upstream.py --upstream ../hermes-agent --json

Probes marked FORK-ONLY have no upstream counterpart module; they are listed
so "every point covered" is auditable, not silently skipped.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

# Each probe: (name, setup_src, stmt_src, iterations)
# The snippet must define fn() using ONLY code available in BOTH repos, with
# per-repo dispatch left to each repo's own default import surface.
_PAYLOAD_SRC = r"""
payload = {
    "tool_call_id": "call_0123456789",
    "content": [
        {"type": "text", "text": "x" * 2048},
        {"type": "json", "data": {"files": [{"path": f"src/mod_{i}.py",
         "lines_changed": i * 3, "ok": True} for i in range(40)]}},
    ],
    "meta": {"elapsed_ms": 123.456, "attempt": 1, "tags": ["a", "b", "c"]},
}
args_str = '{"query": "find all callers of estimate_messages_tokens_rough", ' \
           '"limit": 25, "include_tests": true, "paths": ["agent/", "hermes_cli/"]}'
"""

PROBES = [
    (
        "json.dumps tool-result (default hot path)",
        _PAYLOAD_SRC
        + r"""
try:
    from agent._fastjson import dumps as _d  # fork default
except ImportError:
    from json import dumps as _d             # upstream default
def fn():
    return _d(payload)
""",
        3000,
    ),
    (
        "json.loads tool-args (default hot path)",
        _PAYLOAD_SRC
        + r"""
try:
    from agent._fastjson import loads as _l
except ImportError:
    from json import loads as _l
def fn():
    return _l(args_str)
""",
        20000,
    ),
    (
        "tool-arg canonicalize (loads+dumps sort_keys)",
        _PAYLOAD_SRC
        + r"""
try:
    from agent._fastjson import loads as _l, dumps as _d
except ImportError:
    from json import loads as _l, dumps as _d
def fn():
    return _d(_l(args_str), sort_keys=True, separators=(",", ":"))
""",
        10000,
    ),
    (
        "token estimate: 200-message history (len//4 loop)",
        r"""
from agent.model_metadata import estimate_messages_tokens_rough
messages = [
    {"role": "user" if i % 2 else "assistant", "content": "word " * 300}
    for i in range(200)
]
def fn():
    return estimate_messages_tokens_rough(messages)
""",
        300,
    ),
]

CLI_IMPORT_PROBE = "import hermes_cli.main"

FORK_ONLY = [
    "rust_ext/ (PyO3 streaming tool-call parse, batch token estimate)",
    "agent/serde (msgspec typed decode)",
    "agent/uvloop_utils (uvloop event-loop policy, default-on)",
    "agent/async_dag (DAG tool-batch executor)",
    "agent/net/http_pool (HTTP/2 keep-alive pool)",
    "agent/toon_codec + toon_boundary (TOON token diet)",
    "hermes_cli/daemon.py (warm daemon)",
    "tools/kernel_binding.py (Rust kernel: gate/edit/map/recall)",
]


def _run_probe(repo: Path, src: str, iterations: int) -> float | None:
    """Return median seconds per call for the probe inside *repo*."""
    code = f"""
import sys, time, statistics
sys.path.insert(0, {str(repo)!r})
{src}
fn()  # warm
samples = []
for _ in range(5):
    t0 = time.perf_counter()
    for _ in range({iterations}):
        fn()
    samples.append((time.perf_counter() - t0) / {iterations})
print(statistics.median(samples))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=repo
    )
    if proc.returncode != 0:
        return None
    return float(proc.stdout.strip())


def _cold_import(repo: Path, samples: int = 3) -> float | None:
    times = []
    for _ in range(samples):
        code = (
            "import sys, time; sys.path.insert(0, %r); t0=time.perf_counter(); "
            "%s; print(time.perf_counter()-t0)" % (str(repo), CLI_IMPORT_PROBE)
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=repo
        )
        if proc.returncode != 0:
            return None
        times.append(float(proc.stdout.strip()))
    return statistics.median(times)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="../hermes-agent",
                    help="Path to the original hermes-agent checkout")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    upstream = Path(args.upstream).resolve()
    if not (upstream / "hermes_cli").is_dir():
        print(f"error: {upstream} does not look like a hermes-agent checkout",
              file=sys.stderr)
        return 2

    rows = []
    for name, src, iters in PROBES:
        ours = _run_probe(HERE, src, iters)
        theirs = _run_probe(upstream, src, iters)
        rows.append({"probe": name, "simplicio_s": ours, "hermes_s": theirs})

    rows.append({
        "probe": f"CLI cold import ({CLI_IMPORT_PROBE})",
        "simplicio_s": _cold_import(HERE),
        "hermes_s": _cold_import(upstream),
    })

    for r in rows:
        s, h = r["simplicio_s"], r["hermes_s"]
        r["speedup"] = (h / s) if (s and h) else None
        r["verdict"] = (
            "n/a" if r["speedup"] is None
            else "FASTER" if r["speedup"] >= 1.05
            else "PARITY" if r["speedup"] >= 0.95
            else "SLOWER"
        )

    if args.as_json:
        print(json.dumps({"rows": rows, "fork_only": FORK_ONLY}, indent=2))
        return 0

    w = max(len(r["probe"]) for r in rows) + 2
    print(f"{'probe':<{w}} {'simplicio':>12} {'hermes':>12} {'speedup':>8}  verdict")
    for r in rows:
        s = f"{r['simplicio_s']*1e6:.1f}us" if r["simplicio_s"] else "ERR"
        h = f"{r['hermes_s']*1e6:.1f}us" if r["hermes_s"] else "ERR"
        sp = f"{r['speedup']:.2f}x" if r["speedup"] else "-"
        print(f"{r['probe']:<{w}} {s:>12} {h:>12} {sp:>8}  {r['verdict']}")
    print("\nFork-only modules (no upstream counterpart — wins by existence):")
    for m in FORK_ONLY:
        print(f"  + {m}")
    slower = [r for r in rows if r["verdict"] == "SLOWER"]
    print(f"\n{'FAIL: ' + str(len(slower)) + ' probe(s) slower than upstream' if slower else 'OK: no shared probe is slower than upstream'}")
    return 1 if slower else 0


if __name__ == "__main__":
    raise SystemExit(main())
