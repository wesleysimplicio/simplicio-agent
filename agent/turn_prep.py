"""Preparação de turno isolada (issue #221, vertical slice).

Extrai a responsabilidade de 'preparação de turno' (setup de clients, budgets,
context) para fora do AIAgent god-file, preservando a fachada. O AIAgent pode
chamar prepare_turn(agent, session) para popular agent.turn_context e
agent.iteration_budget sem montar um objeto AIAgent gigante nos testes.

Não refatora run_agent.py inteiro — só este seam, com contrato estável.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TurnPrepContext:
    session_id: str
    turn_id: str
    budget: Dict[str, Any] = field(default_factory=dict)
    clients: Dict[str, Any] = field(default_factory=dict)
    prepared_at: float = field(default_factory=time.monotonic)
    ready: bool = False


# Chaves de budget com defaults sensatos (não quebra o budget governor existente).
_DEFAULT_BUDGET = {
    "max_iterations": 90,
    "tool_timeout_s": 120.0,
    "headroom": 10,
}


def prepare_turn(
    agent: Any,
    session: Any,
    *,
    overrides: Optional[Dict[str, Any]] = None,
) -> TurnPrepContext:
    """Popula agent.turn_context e agent.iteration_budget.

    Aceita qualquer objeto que aceite atribuição de atributos (AIAgent real ou
    stub de teste). Não importa run_agent.py.
    """
    raw_sid = getattr(session, "session_id", None)
    session_id = raw_sid or "default"
    budget = dict(_DEFAULT_BUDGET)
    if overrides:
        budget.update(overrides)

    ctx = TurnPrepContext(
        session_id=session_id,
        turn_id=f"{session_id}:{int(time.monotonic()*1e6)}",
        budget=budget,
        clients=getattr(agent, "clients", {}) or {},
    )
    ctx.ready = True

    # attach ao agent (fachada AIAgent consome estes atributos)
    try:
        agent.turn_context = ctx
        agent.iteration_budget = budget
    except Exception:
        # objeto imutável: retorna ctx mesmo assim (caller decide)
        pass
    return ctx


def is_prepared(agent: Any) -> bool:
    ctx = getattr(agent, "turn_context", None)
    return bool(ctx is not None and getattr(ctx, "ready", False))
