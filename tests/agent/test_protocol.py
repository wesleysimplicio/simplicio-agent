"""Focused tests for the AgentHost-to-facade protocol boundary."""

from agent.host import AgentHost
from agent.protocol import AgentProtocol
from run_agent import AIAgent


class CompatibleAgent:
    def run_conversation(
        self, user_message: str, **kwargs: object
    ) -> dict[str, object]:
        return {"final_response": user_message, "kwargs": kwargs}


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

    assert result == {"final_response": "hello", "kwargs": {}}
