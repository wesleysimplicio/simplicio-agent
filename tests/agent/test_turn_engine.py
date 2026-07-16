"""Testes da máquina de estados TurnEngine (issue #227)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent.conversation_loop as conversation_loop

from agent.turn_engine import (
    TurnContext,
    TurnEngine,
    TurnPhase,
    TurnTransitionError,
    mark_tool_call,
    mark_tool_result,
    mark_compress,
    mark_finalize,
    mark_completed,
)


def _ctx() -> TurnContext:
    return TurnContext(turn_id="t1", session_id="s1", phase=TurnPhase.ACCEPTED)


def test_happy_path_valid():
    ctx = _ctx()
    assert mark_tool_call(ctx) == TurnPhase.TOOL_CALL
    assert mark_tool_result(ctx) == TurnPhase.TOOL_RESULT
    assert mark_tool_call(ctx) == TurnPhase.TOOL_CALL
    assert mark_tool_result(ctx) == TurnPhase.TOOL_RESULT
    assert mark_finalize(ctx) == TurnPhase.FINALIZE
    assert mark_completed(ctx) == TurnPhase.COMPLETED
    assert ctx.is_terminal is True


def test_completed_to_tool_call_rejected():
    ctx = _ctx()
    mark_tool_call(ctx)
    mark_finalize(ctx)
    mark_completed(ctx)
    with pytest.raises(TurnTransitionError):
        TurnEngine.transition(ctx, TurnPhase.TOOL_CALL)


def test_cancel_from_any_phase():
    ctx = _ctx()
    mark_tool_call(ctx)
    mark_tool_result(ctx)
    mark_compress(ctx)
    assert TurnEngine.cancel(ctx) == TurnPhase.CANCELLED
    assert ctx.cancelled is True
    assert ctx.is_terminal is True
    # terminal não sai
    with pytest.raises(TurnTransitionError):
        TurnEngine.transition(ctx, TurnPhase.STARTED)


def test_compress_only_after_tool_loop():
    ctx = _ctx()
    # COMPRESS não é alcançável direto de ACCEPTED/STARTED
    assert TurnEngine.can_transition(ctx, TurnPhase.COMPRESS) is False
    mark_tool_call(ctx)
    assert TurnEngine.can_transition(ctx, TurnPhase.COMPRESS) is True


def test_terminal_states_do_not_leave():
    for term in (TurnPhase.COMPLETED, TurnPhase.FAILED, TurnPhase.CANCELLED):
        ctx = TurnContext(turn_id="x", phase=term)
        assert ctx.is_terminal is True
        assert TurnEngine.can_transition(ctx, TurnPhase.STARTED) is False


def _run_wrapped_turn(monkeypatch, result):
    import agent.telemetry.turn_metrics as turn_metrics

    monkeypatch.setattr(turn_metrics, "finalize_and_record_turn", lambda agent: None)
    agent = SimpleNamespace(_interrupt_requested=False)

    @conversation_loop._record_turn_metrics
    def wrapped(current_agent):
        current_agent.context = conversation_loop._start_turn_engine(
            turn_id="t1", session_id="s1"
        )
        return result

    return agent, wrapped(agent)


def test_real_loop_boundary_terminalizes_completed_result(monkeypatch):
    agent, result = _run_wrapped_turn(
        monkeypatch, {"completed": True, "failed": False}
    )

    assert result["completed"] is True
    assert agent.context.phase is TurnPhase.COMPLETED
    assert agent.context.history == [
        TurnPhase.ACCEPTED,
        TurnPhase.STARTED,
        TurnPhase.FINALIZE,
    ]
    assert conversation_loop._ACTIVE_TURN_ENGINE_CONTEXT.get() is None


def test_real_loop_boundary_terminalizes_cancelled_result(monkeypatch):
    agent, _ = _run_wrapped_turn(
        monkeypatch, {"completed": False, "failed": False, "interrupted": True}
    )

    assert agent.context.phase is TurnPhase.CANCELLED
    assert agent.context.cancelled is True


def test_real_loop_boundary_terminalizes_failed_result(monkeypatch):
    agent, _ = _run_wrapped_turn(
        monkeypatch, {"completed": False, "failed": True, "interrupted": False}
    )

    assert agent.context.phase is TurnPhase.FAILED


def test_real_loop_boundary_terminalizes_exception_and_preserves_error(monkeypatch):
    import agent.telemetry.turn_metrics as turn_metrics

    monkeypatch.setattr(turn_metrics, "finalize_and_record_turn", lambda agent: None)
    agent = SimpleNamespace(_interrupt_requested=False)

    @conversation_loop._record_turn_metrics
    def wrapped(current_agent):
        current_agent.context = conversation_loop._start_turn_engine(
            turn_id="t1", session_id="s1"
        )
        raise RuntimeError("provider fault")

    with pytest.raises(RuntimeError, match="provider fault"):
        wrapped(agent)

    assert agent.context.phase is TurnPhase.FAILED
    assert conversation_loop._ACTIVE_TURN_ENGINE_CONTEXT.get() is None
