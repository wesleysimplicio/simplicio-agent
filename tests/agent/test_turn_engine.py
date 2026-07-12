"""Testes da máquina de estados TurnEngine (issue #227)."""
from __future__ import annotations

import pytest

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
