"""Testes de prepare_turn (issue #221, vertical slice de modularização AIAgent)."""
from __future__ import annotations

from types import SimpleNamespace

from agent.turn_prep import TurnPrepContext, is_prepared, prepare_turn


class _StubSession:
    def __init__(self, sid="s1"):
        self.session_id = sid


class _StubAgent:
    def __init__(self):
        self.clients = {"provider": object()}
        self.turn_context = None
        self.iteration_budget = None


def test_prepare_populates_turn_context_and_budget():
    agent = _StubAgent()
    session = _StubSession()
    ctx = prepare_turn(agent, session)
    assert isinstance(ctx, TurnPrepContext)
    assert agent.turn_context is ctx
    assert agent.iteration_budget == ctx.budget
    assert agent.iteration_budget["max_iterations"] == 90
    assert agent.iteration_budget["tool_timeout_s"] == 120.0
    assert is_prepared(agent) is True


def test_prepare_is_stable_and_overridable():
    agent = _StubAgent()
    session = _StubSession("sX")
    ctx = prepare_turn(agent, session, overrides={"max_iterations": 5})
    assert ctx.budget["max_iterations"] == 5
    # default preservado
    assert ctx.budget["headroom"] == 10


def test_prepare_without_session_uses_default():
    agent = _StubAgent()
    ctx = prepare_turn(agent, SimpleNamespace(session_id=None))
    assert ctx.session_id == "default"
