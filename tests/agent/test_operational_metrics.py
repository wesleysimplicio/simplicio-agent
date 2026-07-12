"""Testes para agent/operational_metrics.py (issue #184).

Prova:
  (a) continuity detecta efeito duplicado;
  (b) latency_aggregate agrega amostras de TurnLatencyProbe;
  (c) cada indicador tem falsifier definido (não vazio).
"""

from __future__ import annotations

import pytest

from agent.operational_metrics import (
    ALL_INDICATORS,
    CONTINUITY_SPEC,
    LATENCY_SPEC,
    TASK_SUCCESS_SPEC,
    continuity_score,
    latency_aggregate,
    task_success_rate,
    validate_all_indicators,
)
from agent.perf_probe import TurnLatencySample


# ---------------------------------------------------------------------------
# (a) continuity — detecção de efeito duplicado
# ---------------------------------------------------------------------------
def test_continuity_preserves_unique_effects():
    effects = ["file:write:a.md@v1", "file:write:b.md@v1"]
    reading = continuity_score(effects)
    assert reading.value == 1.0
    assert reading.passed is True
    assert "0" in reading.detail  # zero duplicatas


def test_continuity_detects_duplicate_effect():
    """FALSIFIER (a): re-aplicar efeito já aplicado deve derrubar continuity."""
    effects = [
        "file:write:README.md@v2",  # turno 1
        "file:write:README.md@v2",  # turno 2 — duplicata!
        "file:write:other.md@v1",
    ]
    reading = continuity_score(effects)
    # 2 únicos / 3 totais = 0.666... < threshold (1.0)
    assert reading.value < 1.0
    assert reading.passed is False
    assert "duplicates=1" in reading.detail


def test_continuity_empty_is_vacuously_preserved():
    reading = continuity_score([])
    assert reading.value == 1.0
    assert reading.passed is True


# ---------------------------------------------------------------------------
# (b) latency_aggregate — agrega amostras do TurnLatencyProbe
# ---------------------------------------------------------------------------
def _sample(total_s: float, api_calls: int = 1) -> TurnLatencySample:
    s = TurnLatencySample(api_calls=api_calls)
    s.total_seconds = total_s
    return s


def test_latency_aggregate_computes_p95_and_mean():
    """FALSIFIER (b): agrega amostras do perf_probe corretamente."""
    samples = [_sample(0.010), _sample(0.030)]  # 10ms, 30ms
    reading = latency_aggregate(samples)
    # p95 de [10, 30] com interpolação linear = 10 + (30-10)*0.95 = 29.0
    assert reading.value == pytest.approx(29.0, abs=0.5)
    assert reading.detail.startswith("p50=")
    assert "api_calls_total=2" in reading.detail


def test_latency_aggregate_single_sample():
    reading = latency_aggregate([_sample(0.050, api_calls=3)])
    assert reading.value == pytest.approx(50.0, abs=1e-6)
    assert "api_calls_total=3" in reading.detail


def test_latency_aggregate_empty():
    reading = latency_aggregate([])
    assert reading.value == 0.0
    assert reading.passed is True
    assert "no samples" in reading.detail


def test_latency_aggregate_threshold_fail():
    # turno de 40s estoura o threshold de 30s (p95)
    samples = [_sample(0.010), _sample(40.0)]
    reading = latency_aggregate(samples)
    assert reading.value > LATENCY_SPEC.threshold
    assert reading.passed is False


# ---------------------------------------------------------------------------
# (c) cada indicador tem falsifier definido (não vazio)
# ---------------------------------------------------------------------------
def test_every_indicator_has_nonempty_falsifier():
    """FALSIFIER (c): todo indicador deve ter falsifier não-vazio."""
    for spec in ALL_INDICATORS:
        assert spec.falsifier, f"Indicator '{spec.name}' has empty falsifier"
        assert spec.falsifier.strip()


def test_validate_all_indicators_passes():
    # Não deve lançar ValueError
    validate_all_indicators()


def test_indicator_specs_metadata_present():
    for spec in (CONTINUITY_SPEC, LATENCY_SPEC, TASK_SUCCESS_SPEC):
        assert spec.name
        assert spec.definition.strip()
        assert spec.unit.strip()
        assert isinstance(spec.threshold, float)


def test_task_success_rate_threshold():
    """Complementa (c): task_success aplica o threshold do falsifier."""
    reading = task_success_rate([True, False, False])  # 1/3 = 0.333
    assert reading.value == pytest.approx(1 / 3, abs=1e-9)
    assert reading.passed is False  # 0.333 < 0.8


def test_task_success_rate_pass():
    reading = task_success_rate([True, True, True, True, False])  # 4/5 = 0.8
    assert reading.value == pytest.approx(0.8, abs=1e-9)
    assert reading.passed is True
