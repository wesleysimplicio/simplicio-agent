"""Focused tests for the AgentHost-to-facade protocol boundary."""

from agent.host import AgentHost
from agent.protocol import AgentConversationResult, AgentProtocol, HostTurnRequest
from run_agent import AIAgent


class CompatibleAgent:
    def run_conversation(
        self, user_message: str, **kwargs: object
    ) -> AgentConversationResult:
        return {
            "final_response": user_message,
            "messages": [{"role": "assistant", "content": user_message}],
            "completed": not kwargs,
        }


class IncompatibleAgent:
    pass


def test_agent_protocol_is_minimal_and_structural() -> None:
    assert isinstance(CompatibleAgent(), AgentProtocol)
    assert not isinstance(IncompatibleAgent(), AgentProtocol)


def test_public_aia_agent_preserves_the_protocol_surface() -> None:
    assert isinstance(AIAgent.__new__(AIAgent), AgentProtocol)


def test_agent_host_accepts_any_compatible_agent_facade() -> None:
    host = AgentHost(lambda _identity: CompatibleAgent())
    try:
        result = host.run_turn("default", "session", "hello", idempotency_key="turn-1")
    finally:
        host.shutdown()

    assert result == {
        "final_response": "hello",
        "messages": [{"role": "assistant", "content": "hello"}],
        "completed": True,
    }


def test_host_turn_request_normalizes_daemon_payload_shape() -> None:
    request = HostTurnRequest.from_mapping(
        {
            "op": "turn.start",
            "session_id": "session-1",
            "message": "hello",
            "idempotency_key": "turn-1",
            "turn_id": "turn-1",
            "attempt_id": "attempt-2",
            "revision": "7",
            "conversation_history": [{"role": "user", "content": "before"}],
            "timeout": 30,
        },
        default_profile="desktop",
    )

    assert request == HostTurnRequest(
        profile="desktop",
        session_id="session-1",
        user_message="hello",
        idempotency_key="turn-1",
        turn_id="turn-1",
        attempt_id="attempt-2",
        revision=7,
        conversation_kwargs={
            "conversation_history": [{"role": "user", "content": "before"}],
        },
    )
