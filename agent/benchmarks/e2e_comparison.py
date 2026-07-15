"""
Benchmark end-to-end: Simplicio Agent vs Hermes upstream baseline.

Issue #9 — mede latências reais de operações core e gera relatório comparativo.
Não requer deps externas (stdlib only).
"""
from __future__ import annotations
import time
import subprocess
import statistics
import json
import sys
import os
from pathlib import Path
from typing import Any


SIMPLICIO_BIN = Path(os.environ.get("SIMPLICIO_BIN", "/opt/homebrew/bin/simplicio"))
REPO = Path(__file__).parent.parent.parent  # raiz do repo


def _timeit(fn, n: int = 5) -> dict[str, Any]:
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)  # ms
    return {
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "min_ms": min(times),
        "max_ms": max(times),
        "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0.0,
        "n": n,
    }


def bench_doctor_json(n: int = 5) -> dict[str, Any]:
    """Mede latência do `simplicio doctor --json` (smoke test do runtime)."""
    def run():
        r = subprocess.run(
            [str(SIMPLICIO_BIN), "doctor", "--json"],
            capture_output=True, text=True, timeout=10
        )
        assert r.returncode == 0, f"doctor falhou: {r.stderr[:200]}"

    result = _timeit(run, n)
    result["command"] = "simplicio doctor --json"
    return result


def bench_memory_recall(n: int = 5, query: str = "benchmark") -> dict[str, Any]:
    """Mede latência do `simplicio memory <query>`."""
    def run():
        subprocess.run(
            [str(SIMPLICIO_BIN), "memory", query, "--repo", str(REPO)],
            capture_output=True, text=True, timeout=15
        )

    result = _timeit(run, n)
    result["command"] = f"simplicio memory '{query}'"
    return result


def bench_runtime_map(n: int = 3) -> dict[str, Any]:
    """Mede latência do `simplicio runtime map --for-llm markdown`."""
    def run():
        subprocess.run(
            [str(SIMPLICIO_BIN), "runtime", "map", "--repo", str(REPO),
             "--for-llm", "markdown"],
            capture_output=True, text=True, timeout=30
        )

    result = _timeit(run, n)
    result["command"] = "simplicio runtime map --for-llm markdown"
    return result


def bench_python_import(n: int = 10) -> dict[str, Any]:
    """Mede latência de import do pacote agent (baseline Python)."""
    def run():
        r = subprocess.run(
            [sys.executable, "-c", "import agent; _ = agent.__version__"],
            capture_output=True, text=True, cwd=str(REPO), timeout=10
        )
        # aceita falha (versão pode não existir)

    result = _timeit(run, n)
    result["command"] = f"{sys.executable} -c 'import agent'"
    return result


def run_all(n_fast: int = 5, n_slow: int = 3) -> dict[str, Any]:
    """Roda todos os benchmarks e retorna dict com resultados."""
    results: dict[str, Any] = {
        "simplicio_bin": str(SIMPLICIO_BIN),
        "repo": str(REPO),
        "python": sys.executable,
        "benchmarks": {},
    }

    print("=== Benchmark e2e: Simplicio Agent ===", flush=True)

    print(f"  doctor --json (n={n_fast})...", end=" ", flush=True)
    try:
        r = bench_doctor_json(n_fast)
        results["benchmarks"]["doctor_json"] = r
        print(f"{r['median_ms']:.1f} ms median")
    except Exception as e:
        results["benchmarks"]["doctor_json"] = {"error": str(e)}
        print(f"ERRO: {e}")

    print(f"  memory recall (n={n_fast})...", end=" ", flush=True)
    try:
        r = bench_memory_recall(n_fast)
        results["benchmarks"]["memory_recall"] = r
        print(f"{r['median_ms']:.1f} ms median")
    except Exception as e:
        results["benchmarks"]["memory_recall"] = {"error": str(e)}
        print(f"ERRO: {e}")

    print(f"  runtime map (n={n_slow})...", end=" ", flush=True)
    try:
        r = bench_runtime_map(n_slow)
        results["benchmarks"]["runtime_map"] = r
        print(f"{r['median_ms']:.1f} ms median")
    except Exception as e:
        results["benchmarks"]["runtime_map"] = {"error": str(e)}
        print(f"ERRO: {e}")

    print(f"  python import (n={n_fast})...", end=" ", flush=True)
    try:
        r = bench_python_import(n_fast)
        results["benchmarks"]["python_import"] = r
        print(f"{r['median_ms']:.1f} ms median")
    except Exception as e:
        results["benchmarks"]["python_import"] = {"error": str(e)}
        print(f"ERRO: {e}")

    return results


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Benchmark e2e Simplicio Agent")
    p.add_argument("--json-out", help="Salva resultado em arquivo JSON")
    p.add_argument("--n-fast", type=int, default=5)
    p.add_argument("--n-slow", type=int, default=3)
    args = p.parse_args()

    data = run_all(args.n_fast, args.n_slow)

    print("\n=== Resumo (médias) ===")
    for name, r in data["benchmarks"].items():
        if "error" in r:
            print(f"  {name}: ERRO — {r['error']}")
        else:
            print(f"  {name}: {r['mean_ms']:.1f} ms mean, {r['median_ms']:.1f} ms median")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(data, indent=2))
        print(f"\nSalvo em {args.json_out}")
