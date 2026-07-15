"""Testes para benchmark e2e Simplicio (issue #9)."""
import sys
import statistics
import subprocess
from pathlib import Path
import pytest

REPO = Path(__file__).parent.parent


def test_bench_doctor_importable():
    """Módulo de benchmark importa sem erro."""
    sys.path.insert(0, str(REPO))
    from agent.benchmarks.e2e_comparison import bench_doctor_json, _timeit
    assert callable(bench_doctor_json)
    assert callable(_timeit)


def test_timeit_returns_correct_keys():
    """_timeit retorna dict com campos esperados."""
    sys.path.insert(0, str(REPO))
    from agent.benchmarks.e2e_comparison import _timeit

    calls = []
    def noop():
        calls.append(1)

    result = _timeit(noop, n=3)
    assert "mean_ms" in result
    assert "median_ms" in result
    assert "min_ms" in result
    assert "max_ms" in result
    assert "n" in result
    assert result["n"] == 3
    assert len(calls) == 3
    assert result["mean_ms"] >= 0
    assert result["min_ms"] <= result["median_ms"] <= result["max_ms"]


def test_bench_python_import_runs():
    """bench_python_import executa e retorna latência > 0."""
    sys.path.insert(0, str(REPO))
    from agent.benchmarks.e2e_comparison import bench_python_import

    result = bench_python_import(n=2)
    assert "mean_ms" in result
    assert result["mean_ms"] > 0
    assert "command" in result


def test_bench_doctor_json_runs():
    """bench_doctor_json executa contra binário real."""
    sys.path.insert(0, str(REPO))
    from agent.benchmarks.e2e_comparison import bench_doctor_json, SIMPLICIO_BIN

    if not SIMPLICIO_BIN.exists():
        pytest.skip(f"simplicio não encontrado em {SIMPLICIO_BIN}")

    result = bench_doctor_json(n=2)
    assert result["median_ms"] > 0
    assert result["min_ms"] <= result["median_ms"]
    print(f"\n  doctor --json: {result['median_ms']:.1f} ms median")


def test_run_all_structure():
    """run_all retorna estrutura com benchmarks dict."""
    sys.path.insert(0, str(REPO))
    from agent.benchmarks.e2e_comparison import run_all, SIMPLICIO_BIN

    if not SIMPLICIO_BIN.exists():
        pytest.skip(f"simplicio não encontrado em {SIMPLICIO_BIN}")

    data = run_all(n_fast=2, n_slow=1)
    assert "benchmarks" in data
    assert "simplicio_bin" in data
    assert isinstance(data["benchmarks"], dict)
    # pelo menos 1 benchmark rodou
    assert len(data["benchmarks"]) >= 1
