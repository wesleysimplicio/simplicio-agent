from __future__ import annotations

from agent.host import SessionIdentity
from tui_gateway import server


class FakeTuiAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run_conversation(self, message: str, **kwargs):
        self.calls.append((message, kwargs))
        return {"final_response": message, "completed": True}


def _close_test_host(session: dict, sid: str) -> None:
    server._sessions.pop(sid, None)
    host = server._tui_agent_host
    if host is not None:
        host.shutdown()
    server._tui_agent_host = None


def test_tui_turns_use_one_agenthost_entry_and_preserve_turn_contract():
    sid = "host-bridge-test"
    session_key = "tui-host-bridge-session"
    agent = FakeTuiAgent()
    session = {
        "session_key": session_key,
        "source": "tui",
        "agent": agent,
    }
    server._sessions[sid] = session
    try:
        first = server._run_tui_turn(
            session,
            "first",
            turn_id="turn-1",
            conversation_kwargs={"task_id": session_key},
        )
        second = server._run_tui_turn(
            session,
            "second",
            turn_id="turn-2",
            conversation_kwargs={"task_id": session_key},
        )

        assert first["final_response"] == "first"
        assert second["final_response"] == "second"
        assert agent.calls == [
            ("first", {"task_id": session_key}),
            ("second", {"task_id": session_key}),
        ]
        host = server._tui_agent_host
        assert host is not None
        assert host.pool.is_present(
            SessionIdentity("surface:tui", session_key)
        )
    finally:
        _close_test_host(session, sid)


def test_tui_host_entry_can_be_rebuilt_after_agent_replacement():
    sid = "host-bridge-reset-test"
    session_key = "tui-host-reset-session"
    old_agent = FakeTuiAgent()
    new_agent = FakeTuiAgent()
    session = {"session_key": session_key, "source": "tui", "agent": old_agent}
    server._sessions[sid] = session
    try:
        server._run_tui_turn(
            session,
            "before",
            turn_id="turn-before",
            conversation_kwargs={},
        )
        server._forget_tui_host_session(session)
        session["agent"] = new_agent
        server._run_tui_turn(
            session,
            "after",
            turn_id="turn-after",
            conversation_kwargs={},
        )

        assert old_agent.calls == [("before", {})]
        assert new_agent.calls == [("after", {})]
    finally:
        _close_test_host(session, sid)
