"""Unified cron/scheduling — issue #44.

CronEntry  : dataclass que representa uma tarefa agendada.
UnifiedScheduler: gerencia entradas, calcula próxima execução.

Parser de expressão cron: 5 campos (min hora dia mês dia-semana).
Apenas stdlib — nenhuma dependência externa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CronEntry:
    """Representa uma tarefa agendada no scheduler unificado.

    Campos
    ------
    id         : identificador único (string).
    expression : expressão cron de 5 campos ("min hora dia mês dia-semana").
    task_fn    : callable que será invocado quando a tarefa disparar.
    enabled    : flag que pausa/retoma a entrada sem removê-la.
    """

    id: str
    expression: str
    task_fn: Callable[[], None]
    enabled: bool = True


# ---------------------------------------------------------------------------
# Parser de expressão cron
# ---------------------------------------------------------------------------

def _parse_field(token: str, lo: int, hi: int) -> List[int]:
    """Converte um campo de expressão cron numa lista de inteiros válidos.

    Suporta:
      *        → todos os valores no intervalo [lo, hi]
      */N      → passo N a partir de lo
      a-b      → intervalo a até b (inclusive)
      a-b/N    → intervalo com passo
      a,b,c    → lista explícita
    """
    if "," in token:
        values: List[int] = []
        for part in token.split(","):
            values.extend(_parse_field(part.strip(), lo, hi))
        return sorted(set(values))

    if token == "*":
        return list(range(lo, hi + 1))

    step_match = re.fullmatch(r"(\*|\d+(?:-\d+)?)/(\d+)", token)
    if step_match:
        base, step = step_match.group(1), int(step_match.group(2))
        if step == 0:
            raise ValueError(f"Passo zero inválido em '{token}'")
        if base == "*":
            start, end = lo, hi
        else:
            parts = base.split("-")
            start = int(parts[0])
            end = int(parts[1]) if len(parts) == 2 else hi
        return list(range(start, end + 1, step))

    range_match = re.fullmatch(r"(\d+)-(\d+)", token)
    if range_match:
        a, b = int(range_match.group(1)), int(range_match.group(2))
        return list(range(a, b + 1))

    if re.fullmatch(r"\d+", token):
        v = int(token)
        if not (lo <= v <= hi):
            raise ValueError(f"Valor {v} fora do intervalo [{lo}, {hi}]")
        return [v]

    raise ValueError(f"Token de expressão cron inválido: '{token}'")


def parse_cron_expression(expression: str) -> Dict[str, List[int]]:
    """Faz o parse de uma expressão cron de 5 campos.

    Retorna dict com chaves: minute, hour, day, month, weekday.

    Raises
    ------
    ValueError
        Se a expressão não tiver exatamente 5 campos.
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"Expressão cron deve ter 5 campos, recebeu {len(parts)}: '{expression}'"
        )
    minute_tok, hour_tok, day_tok, month_tok, weekday_tok = parts
    return {
        "minute": _parse_field(minute_tok, 0, 59),
        "hour": _parse_field(hour_tok, 0, 23),
        "day": _parse_field(day_tok, 1, 31),
        "month": _parse_field(month_tok, 1, 12),
        "weekday": _parse_field(weekday_tok, 0, 6),  # 0=dom … 6=sáb
    }


# ---------------------------------------------------------------------------
# Scheduler unificado
# ---------------------------------------------------------------------------

class UnifiedScheduler:
    """Gerencia um conjunto de CronEntry e calcula próximas execuções.

    Uso típico
    ----------
    >>> scheduler = UnifiedScheduler()
    >>> entry = CronEntry(id="daily", expression="0 9 * * *", task_fn=lambda: None)
    >>> scheduler.add(entry)
    >>> scheduler.get_next_run(entry)  # próximo disparo após agora
    datetime.datetime(...)
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, CronEntry] = {}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def add(self, entry: CronEntry) -> None:
        """Adiciona (ou substitui) uma CronEntry pelo seu id."""
        # Valida a expressão logo na inserção para falhar cedo.
        parse_cron_expression(entry.expression)
        self._jobs[entry.id] = entry

    def remove(self, job_id: str) -> None:
        """Remove uma CronEntry pelo id.

        Raises
        ------
        KeyError
            Se o id não existir.
        """
        if job_id not in self._jobs:
            raise KeyError(f"Job '{job_id}' não encontrado")
        del self._jobs[job_id]

    def list_jobs(self) -> List[CronEntry]:
        """Retorna lista de todas as CronEntry registradas."""
        return list(self._jobs.values())

    def get_next_run(
        self,
        entry: CronEntry,
        after: Optional[datetime] = None,
    ) -> datetime:
        """Calcula o próximo instante de execução para *entry*.

        Parameters
        ----------
        entry:
            A CronEntry para a qual calcular o próximo disparo.
        after:
            Referência temporal (default: datetime.now() sem tzinfo).

        Returns
        -------
        datetime
            O próximo instante (resolução de 1 minuto) que satisfaz a
            expressão cron, sempre estritamente maior que *after*.

        Raises
        ------
        ValueError
            Se não for possível calcular o próximo disparo em 4 anos.
        """
        fields = parse_cron_expression(entry.expression)
        if after is None:
            after = datetime.now().replace(second=0, microsecond=0)

        # Começa 1 minuto após o instante de referência.
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Limite: 4 anos × 365 dias × 24 h × 60 min = ~2 101 680 iterações.
        limit = candidate + timedelta(days=4 * 365)

        while candidate <= limit:
            if candidate.month not in fields["month"]:
                # Avança para o próximo mês válido.
                candidate = _advance_to_next_month(candidate, fields["month"])
                continue

            if candidate.day not in fields["day"]:
                candidate += timedelta(days=1)
                candidate = candidate.replace(hour=0, minute=0)
                continue

            # weekday: Python usa 0=seg … 6=dom; cron usa 0=dom … 6=sáb.
            py_wd = candidate.weekday()  # 0=seg
            cron_wd = (py_wd + 1) % 7   # converte para 0=dom
            if cron_wd not in fields["weekday"]:
                candidate += timedelta(days=1)
                candidate = candidate.replace(hour=0, minute=0)
                continue

            if candidate.hour not in fields["hour"]:
                candidate += timedelta(hours=1)
                candidate = candidate.replace(minute=0)
                continue

            if candidate.minute not in fields["minute"]:
                candidate += timedelta(minutes=1)
                continue

            return candidate

        raise ValueError(
            f"Não foi possível calcular o próximo disparo para '{entry.expression}' "
            f"nos próximos 4 anos a partir de {after!r}"
        )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _advance_to_next_month(dt: datetime, valid_months: List[int]) -> datetime:
    """Avança *dt* para o primeiro dia/hora do próximo mês válido."""
    month = dt.month
    year = dt.year
    for _ in range(13):
        month += 1
        if month > 12:
            month = 1
            year += 1
        if month in valid_months:
            return datetime(year, month, 1, 0, 0)
    # Não deve acontecer se a expressão tiver ≥ 1 mês válido.
    raise ValueError("Nenhum mês válido encontrado na expressão cron")
