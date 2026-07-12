"""Indicadores funcionais de 'consciência operacional' (não senciência).

Issue #184 [P0][Benchmark].

Estes indicadores medem propriedades observáveis e testáveis do comportamento
do agente em runtime — NÃO afirmam, sequer sugerem, qualquer estado mental,
qualia ou senciência. São métricas de engenharia: continuidade de efeitos,
agregação de latência/tokens/recursos, e sucesso de tarefa por turno.

Cada indicador é uma dataclass com:
  - ``definition``: o que mede, em linguagem operacional.
  - ``unit``: unidade da leitura (ex.: "ratio", "ms", "bool").
  - ``threshold``: valor-limite; o indicador "passa" quando ``value`` o respeita.
  - ``falsifier``: descrição do teste que provaria a métrica FALSA (vazia NÃO
    é permitida — um indicador sem falsifier não é cientificamente testável).

Nenhuma infraestrutura pesada é criada aqui: só as funções de cálculo e os
objetos de definição. O TurnLatencyProbe (agent/perf_probe.py) já coleta as
amostras de latência; este módulo apenas as agrega.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from agent.perf_probe import TurnLatencySample


# ---------------------------------------------------------------------------
# Tipos base
# ---------------------------------------------------------------------------
@dataclass
class MetricReading:
    """Resultado de um indicador para um turno (ou janela de turnos)."""

    name: str
    value: float
    unit: str
    threshold: float
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "unit": self.unit,
            "threshold": self.threshold,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class IndicatorSpec:
    """Especificação estática de um indicador (o que mede + como refutá-lo)."""

    name: str
    definition: str
    unit: str
    threshold: float
    falsifier: str

    def validate(self) -> None:
        """Garante que o indicador é refutável (falsifier não-vazio)."""
        if not self.falsifier or not self.falsifier.strip():
            raise ValueError(
                f"Indicator '{self.name}' has an empty falsifier — "
                "unfalsifiable indicators are not scientifically testable."
            )


# ---------------------------------------------------------------------------
# (1) continuity — compromissos preservados vs efeitos duplicados
# ---------------------------------------------------------------------------
CONTINUITY_SPEC = IndicatorSpec(
    name="continuity",
    definition=(
        "Mede se o agente repete um efeito já aplicado. A cada turno, o agente "
        "declara os 'efeitos' (ids determinísticos de mudança de estado externa) "
        "que pretende aplicar. continuity = efeitos únicos preservados / efeitos "
        "totais aplicados. 1.0 significa zero duplicação; < 1.0 indica que o "
        "agente re-aplicou um efeito já aplicado anteriormente na mesma sessão."
    ),
    unit="ratio",  # 0.0 .. 1.0
    threshold=1.0,  # exige zero duplicação
    falsifier=(
        "Dado um histórico onde o efeito 'file:write:README.md@v2' já foi "
        "aplicado no turno 1, se o turno 2 declarar novamente "
        "'file:write:README.md@v2' como um efeito novo, continuity deve cair "
        "para < 1.0 (detecção de duplicata). Se continuity ficar em 1.0, a "
        "métrica é falsa (não detecta duplicação)."
    ),
)


def continuity_score(applied_effects: Sequence[str]) -> MetricReading:
    """Calcula continuity a partir da lista ordenada de efeitos aplicados.

    ``applied_effects`` deve conter, em ordem, o id de cada efeito aplicado
    ao longo da sessão (um efeito repetido aparece mais de uma vez). O score
    é único / total. Detecção de duplicata = presença de ids repetidos.
    """
    total = len(applied_effects)
    if total == 0:
        # Sem efeitos: não há duplicação observável; tratamos como "preservado".
        return MetricReading(
            name=CONTINUITY_SPEC.name,
            value=1.0,
            unit=CONTINUITY_SPEC.unit,
            threshold=CONTINUITY_SPEC.threshold,
            passed=True,
            detail="no effects applied (vacuously preserved)",
        )
    unique = len(set(applied_effects))
    score = unique / total
    return MetricReading(
        name=CONTINUITY_SPEC.name,
        value=score,
        unit=CONTINUITY_SPEC.unit,
        threshold=CONTINUITY_SPEC.threshold,
        passed=score >= CONTINUITY_SPEC.threshold,
        detail=f"{unique}/{total} unique effects; duplicates={total - unique}",
    )


# ---------------------------------------------------------------------------
# (2) latency / tokens / resources — agregação das amostras do TurnLatencyProbe
# ---------------------------------------------------------------------------
LATENCY_SPEC = IndicatorSpec(
    name="latency_aggregate",
    definition=(
        "Agrega as amostras por-turno de TurnLatencySample (agent/perf_probe.py). "
        "Não coleta nada novo: recebe uma janela de amostras e produz p50/p95/"
        "p99/max/mean de total_seconds (ms) e soma de api_calls (proxy de tokens/"
        "recursos). Mede o custo de recurso observado por turno."
    ),
    unit="ms",
    threshold=30000.0,  # p95 de total_seconds não deve passar de 30s/turno
    falsifier=(
        "Dadas duas amostras com total_seconds=10.0 e 30.0, a p95 agregada deve "
        "ser 30.0 (ou 28.5 se interpolada) e a média 20.0. Se a agregação "
        "retornar p95=10.0 (ignorando a segunda amostra) ou média incorreta, a "
        "métrica é falsa (não agrega o perf_probe)."
    ),
)


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    # Interpolação linear simples (mesma abordagem de tools/bench_latency.py).
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def latency_aggregate(samples: Sequence[TurnLatencySample]) -> MetricReading:
    """Agrega uma janela de TurnLatencySample em uma leitura de latência."""
    if not samples:
        return MetricReading(
            name=LATENCY_SPEC.name,
            value=0.0,
            unit=LATENCY_SPEC.unit,
            threshold=LATENCY_SPEC.threshold,
            passed=True,
            detail="no samples",
        )
    totals_ms = [s.total_seconds * 1000.0 for s in samples]
    p95 = _percentile(totals_ms, 95.0)
    mean_ms = sum(totals_ms) / len(totals_ms)
    total_api_calls = sum(s.api_calls for s in samples)
    return MetricReading(
        name=LATENCY_SPEC.name,
        value=p95,
        unit=LATENCY_SPEC.unit,
        threshold=LATENCY_SPEC.threshold,
        passed=p95 <= LATENCY_SPEC.threshold,
        detail=(
            f"p50={_percentile(totals_ms, 50.0):.1f}ms "
            f"p95={p95:.1f}ms p99={_percentile(totals_ms, 99.0):.1f}ms "
            f"max={max(totals_ms):.1f}ms mean={mean_ms:.1f}ms "
            f"api_calls_total={total_api_calls}"
        ),
    )


# ---------------------------------------------------------------------------
# (3) task_success — boolean por turno com threshold
# ---------------------------------------------------------------------------
TASK_SUCCESS_SPEC = IndicatorSpec(
    name="task_success",
    definition=(
        "Booleano por turno: o turno atingiu seu objetivo? A leitura agrega uma "
        "janela de resultados de turno (True/False) no *rate* de sucesso. O "
        "threshold é a fração mínima de turnos bem-sucedidos exigida."
    ),
    unit="bool",  # leitura exposta como rate (0..1) para comparação com threshold
    threshold=0.8,  # >= 80% dos turnos devem ser bem-sucedidos
    falsifier=(
        "Dada a janela [True, False, False] (1/3 sucesso), o rate deve ser "
        "~0.333 e o indicador DEVE falhar (passed=False, pois 0.333 < 0.8). "
        "Se retornar passed=True para essa janela, a métrica é falsa (não "
        "aplica o threshold)."
    ),
)


def task_success_rate(successes: Sequence[bool]) -> MetricReading:
    """Agrega uma janela de resultados de turno no rate de sucesso."""
    total = len(successes)
    if total == 0:
        return MetricReading(
            name=TASK_SUCCESS_SPEC.name,
            value=0.0,
            unit=TASK_SUCCESS_SPEC.unit,
            threshold=TASK_SUCCESS_SPEC.threshold,
            passed=False,
            detail="no turn observations",
        )
    ok = sum(1 for s in successes if s)
    rate = ok / total
    return MetricReading(
        name=TASK_SUCCESS_SPEC.name,
        value=rate,
        unit=TASK_SUCCESS_SPEC.unit,
        threshold=TASK_SUCCESS_SPEC.threshold,
        passed=rate >= TASK_SUCCESS_SPEC.threshold,
        detail=f"{ok}/{total} turns succeeded",
    )


# ---------------------------------------------------------------------------
# Registro de todos os indicadores (para validação em massa dos falsifiers)
# ---------------------------------------------------------------------------
ALL_INDICATORS: List[IndicatorSpec] = [
    CONTINUITY_SPEC,
    LATENCY_SPEC,
    TASK_SUCCESS_SPEC,
]


def validate_all_indicators() -> None:
    """Garante que todo indicador tem definição/unit/threshold/falsifier."""
    for spec in ALL_INDICATORS:
        spec.validate()
        if not spec.definition.strip():
            raise ValueError(f"Indicator '{spec.name}' has empty definition.")
        if not spec.unit.strip():
            raise ValueError(f"Indicator '{spec.name}' has empty unit.")


def all_indicator_names() -> List[str]:
    return [s.name for s in ALL_INDICATORS]
