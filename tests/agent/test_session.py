"""Tests for agent.session."""

import pytest

from agent.session import (
    SESSION_SCHEMA,
    AgentSession,
    SessionIdentity,
    SessionInvariantError,
    SessionSnapshot,
)
from agent.self_model import SelfModelSnapshot
from agent.turn_engine import TurnContext, TurnPhase


def test_session_identity_validation():
    """Test SessionIdentity validation."""
    with pytest.raises(SessionInvariantError):
        SessionIdentity("", "session1")
    with pytest.raises(SessionInvariantError):
        SessionIdentity("profile1", "")
    with pytest.raises(SessionInvariantError):
        SessionIdentity("profile1", "session1", "")
    with pytest.raises(SessionInvariantError):
        SessionIdentity("profile1", "session1", "incarnation1", -1)

    identity = SessionIdentity("profile1", "session1")
    assert identity.profile == "profile1"
    assert identity.session_id == "session1"
    assert identity.incarnation == "default"
    assert identity.revision == 0


def test_session_snapshot_validation():
    """Test SessionSnapshot validation."""
    identity = SessionIdentity("profile1", "session1")
    with pytest.raises(TypeError):
        SessionSnapshot("not_an_identity", "hash1", "hash2", "route1")  # type: ignore
    with pytest.raises(SessionInvariantError):
        SessionSnapshot(identity, "", "hash2", "route1")
    with pytest.raises(SessionInvariantError):
        SessionSnapshot(identity, "hash1", "", "route1")
    with pytest.raises(SessionInvariantError):
        SessionSnapshot(identity, "hash1", "hash2", "")
    with pytest.raises(SessionInvariantError):
        SessionSnapshot(identity, "hash1", "hash2", "route1", bridge_generation=-1)

    snapshot = SessionSnapshot(identity, "hash1", "hash2", "route1")
    assert snapshot.identity == identity
    assert snapshot.schema == SESSION_SCHEMA


def test_session_snapshot_from_parts():
    """Test SessionSnapshot.from_parts()."""
    identity = SessionIdentity("profile1", "session1")
    snapshot = SessionSnapshot.from_parts(
        identity,
        system_prompt="prompt1",
        tool_names=["tool1", "tool2"],
        provider_route="route1",
    )
    assert snapshot.identity == identity
    assert snapshot.system_prompt_hash
    assert snapshot.toolset_hash
    assert snapshot.provider_route == "route1"

    # Test with cognition and bridge_generation
    capability = CapabilityState("test", "test", "test")
    cognition = SelfModelSnapshot("digest1", "tenant1", "identity1", (capability,), {})
    snapshot = SessionSnapshot.from_parts(
        identity,
        system_prompt="prompt1",
        tool_names=["tool1", "tool2"],
        provider_route="route1",
        cognition=cognition,
        bridge_generation=1,
    )
    assert snapshot.cognition_digest == "digest1"
    assert snapshot.bridge_generation == 1


def test_session_snapshot_assert_compatible():
    """Test SessionSnapshot.assert_compatible()."""
    identity = SessionIdentity("profile1", "session1")
    snapshot = SessionSnapshot.from_parts(
        identity,
        system_prompt="prompt1",
        tool_names=["tool1", "tool2"],
        provider_route="route1",
    )

    # Should not raise
    snapshot.assert_compatible(
        system_prompt="prompt1",
        tool_names=["tool1", "tool2"],
        provider_route="route1",
    )

    # Should raise for incompatible changes
    with pytest.raises(SessionInvariantError):
        snapshot.assert_compatible(
            system_prompt="prompt2",
            tool_names=["tool1", "tool2"],
            provider_route="route1",
        )
    with pytest.raises(SessionInvariantError):
        snapshot.assert_compatible(
            system_prompt="prompt1",
            tool_names=["tool1"],
            provider_route="route1",
        )
    with pytest.raises(SessionInvariantError):
        snapshot.assert_compatible(
            system_prompt="prompt1",
            tool_names=["tool1", "tool2"],
            provider_route="route2",
        )


def test_agent_session_lifecycle():
    """Test AgentSession lifecycle."""
    identity = SessionIdentity("profile1", "session1")
    snapshot = SessionSnapshot.from_parts(
        identity,
        system_prompt="prompt1",
        tool_names=["tool1", "tool2"],
        provider_route="route1",
    )
    session = AgentSession(snapshot)
    assert not session.closed
    assert session.active_turns == 0

    # Begin a turn
    turn = session.begin_turn()
    assert isinstance(turn, TurnContext)
    assert session.active_turns == 1

    # Complete the turn
    session.complete_turn(turn)
    assert session.active_turns == 0

    # Close the session
    session.close()
    assert session.closed


def test_agent_session_error_cases():
    """Test AgentSession error cases."""
    identity = SessionIdentity("profile1", "session1")
    snapshot = SessionSnapshot.from_parts(
        identity,
        system_prompt="prompt1",
        tool_names=["tool1", "tool2"],
        provider_route="route1",
    )
    session = AgentSession(snapshot)

    # Cannot begin turn on closed session
    session.close()
    with pytest.raises(SessionInvariantError):
        session.begin_turn()

    # Cannot close with active turns
    session = AgentSession(snapshot)
    turn = session.begin_turn()
    with pytest.raises(SessionInvariantError):
        session.close()

    # Cannot complete/fail/cancel invalid turn
    other_turn = TurnContext("other_turn", "0", "other_session")
    with pytest.raises(SessionInvariantError):
        session.complete_turn(other_turn)
    with pytest.raises(SessionInvariantError):
        session.fail_turn(other_turn)
    with pytest.raises(SessionInvariantError):
        session.cancel_turn(other_turn)

    # Cannot complete/fail/cancel terminal turn
    session = AgentSession(snapshot)
    turn = session.begin_turn()
    turn._phase = TurnPhase.COMPLETED  # type: ignore[attr-defined]
    with pytest.raises(SessionInvariantError):
        session.complete_turn(turn)
    with pytest.raises(SessionInvariantError):
        session.fail_turn(turn)
    with pytest.raises(SessionInvariantError):
        session.cancel_turn(turn)