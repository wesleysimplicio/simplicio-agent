"""Focused contract tests for the issue #221 session/turn boundary."""

from __future__ import annotations

import pytest

from agent.session import (
    AgentSession,
    SessionIdentity,
    SessionInvariantError,
    SessionSnapshot,
)
from agent.turn_engine import TurnEngine, TurnPhase


class _Cognition:
    def __init__(self, digest: str = "cognition-v1") -> None:
        self._digest = digest

    def digest(self) -> str:
        return self._digest


def _snapshot(**changes: object) -> SessionSnapshot:
    identity = SessionIdentity("cli", "s1", incarnation="inc-1", revision=2)
    values = {
        "system_prompt": "stable prompt",
        "tool_names": ["terminal", "read_file"],
        "provider_route": "openai:gpt-5",
        "cognition": _Cognition(),
        "bridge_generation": 3,
    }
    values.update(changes)
    return SessionSnapshot.from_parts(identity, **values)


def test_snapshot_fingerprints_are_stable_and_non_secret() -> None:
    first = _snapshot(tool_names=["read_file", "terminal", "terminal"])
    second = _snapshot(tool_names=["terminal", "read_file"])

    assert first == second
    assert first.system_prompt_hash != "stable prompt"
    assert first.toolset_hash != "terminal"
    assert "stable prompt" not in repr(first)


def test_snapshot_rejects_incarnation_changes() -> None:
    snapshot = _snapshot()

    snapshot.assert_compatible(
        system_prompt="stable prompt",
        tool_names=["read_file", "terminal"],
        provider_route="openai:gpt-5",
        cognition=_Cognition(),
        bridge_generation=3,
    )
    with pytest.raises(SessionInvariantError, match="incarnation changed"):
        snapshot.assert_compatible(
            system_prompt="changed prompt",
            tool_names=["read_file", "terminal"],
            provider_route="openai:gpt-5",
            cognition=_Cognition(),
            bridge_generation=3,
        )


def test_session_owns_turn_identity_and_shared_engine_lifecycle() -> None:
    session = AgentSession(_snapshot())
    context = session.begin_turn(attempt_id="attempt-1")

    assert context.phase is TurnPhase.STARTED
    assert context.session_id == "s1"
    assert session.active_turns == 1

    TurnEngine.transition(context, TurnPhase.TOOL_CALL)
    TurnEngine.transition(context, TurnPhase.TOOL_RESULT)
    completed = session.complete_turn(context)

    assert completed.phase is TurnPhase.COMPLETED
    assert completed.history == [
        TurnPhase.ACCEPTED,
        TurnPhase.STARTED,
        TurnPhase.TOOL_CALL,
        TurnPhase.TOOL_RESULT,
        TurnPhase.FINALIZE,
    ]
    assert session.active_turns == 0


def test_session_rejects_foreign_turns_and_close_with_active_work() -> None:
    session = AgentSession(_snapshot())
    other = AgentSession(_snapshot())
    context = session.begin_turn()

    with pytest.raises(SessionInvariantError, match="not active"):
        other.cancel_turn(context)
    with pytest.raises(SessionInvariantError, match="active turns"):
        session.close()

    session.cancel_turn(context)
    session.close()
    assert session.closed is True
    with pytest.raises(SessionInvariantError, match="closed"):
        session.begin_turn()


def test_failed_turn_is_terminal_and_removed_from_session() -> None:
    session = AgentSession(_snapshot())
    context = session.begin_turn()

    failed = session.fail_turn(context)

    assert failed.phase is TurnPhase.FAILED
    assert failed.is_terminal
    assert session.active_turns == 0
