"""Contract tests for the embedded AgentHost vertical slice."""

from concurrent.futures import wait
from threading import Event

import pytest

from agent.host import AgentHost, HostBackpressure, SessionIdentity
from agent.protocol import HostTurnRequest


class FakeAgent:
    def __init__(self, name, started, release=None):
        self.name = name
        self.started = started
        self.release = release
        self.calls = []

    def run_conversation(self, message, **kwargs):
        self.calls.append((message, kwargs))
        self.started.set()
        if self.release is not None:
            self.release.wait(timeout=2)
        return {"final_response": f"{self.name}:{message}"}


def test_same_session_reuses_agent_and_serializes_turns():
    created = []

    def factory(identity):
        agent = FakeAgent(identity.session_id, Event())
        created.append(agent)
        return agent

    host = AgentHost(factory, max_sessions=4)
    try:
        first = host.submit("p", "s", "one", idempotency_key="one")
        second = host.submit("p", "s", "two", idempotency_key="two")
        assert first.result(timeout=2)["final_response"] == "s:one"
        assert second.result(timeout=2)["final_response"] == "s:two"
        assert len(created) == 1
        assert [call[0] for call in created[0].calls] == ["one", "two"]
    finally:
        host.shutdown()


def test_active_lease_prevents_eviction_and_idle_session_can_evict():
    gate = Event()
    host = AgentHost(lambda identity: FakeAgent(identity.session_id, Event(), gate), max_sessions=1)
    try:
        running = host.submit("p", "held", "work", idempotency_key="held")
        assert host.pool.is_leased(SessionIdentity("p", "held"))
        with pytest.raises(HostBackpressure):
            host.submit("p", "other", "blocked", idempotency_key="other")
        gate.set()
        running.result(timeout=2)
        assert host.pool.evict_idle() == [SessionIdentity("p", "held")]
        assert not host.pool.is_present(SessionIdentity("p", "held"))
    finally:
        host.shutdown()


def test_duplicate_idempotency_key_returns_same_turn_without_duplicate_call():
    created = []
    host = AgentHost(lambda identity: created.append(FakeAgent(identity.session_id, Event())) or created[-1])
    try:
        one = host.submit("p", "s", "once", idempotency_key="same")
        duplicate = host.submit("p", "s", "different", idempotency_key="same")
        assert one is duplicate
        assert one.result(timeout=2)["final_response"] == "s:once"
        assert created[0].calls == [("once", {})]
    finally:
        host.shutdown()


def test_failed_turn_recovers_for_next_turn():
    attempts = []

    class Flaky(FakeAgent):
        def run_conversation(self, message, **kwargs):
            attempts.append(message)
            if len(attempts) == 1:
                raise RuntimeError("provider disconnected")
            return super().run_conversation(message, **kwargs)

    host = AgentHost(lambda identity: Flaky(identity.session_id, Event()))
    try:
        with pytest.raises(RuntimeError, match="provider disconnected"):
            host.submit("p", "s", "fail", idempotency_key="fail").result(timeout=2)
        assert host.submit("p", "s", "recover", idempotency_key="recover").result(timeout=2)["final_response"] == "s:recover"
        assert attempts == ["fail", "recover"]
    finally:
        host.shutdown()


def test_explicit_recovery_rebuilds_idle_agent():
    created = []
    host = AgentHost(lambda identity: created.append(FakeAgent(len(created), Event())) or created[-1])
    try:
        host.run_turn("p", "s", "before", idempotency_key="before")
        assert host.recover("p", "s") is True
        host.run_turn("p", "s", "after", idempotency_key="after")
        assert len(created) == 2
    finally:
        host.shutdown()


def test_profile_isolation_uses_distinct_agents():
    created = []
    host = AgentHost(lambda identity: created.append(identity) or FakeAgent(identity.profile, Event()))
    try:
        assert host.submit("a", "s", "x", idempotency_key="a").result(timeout=2)["final_response"] == "a:x"
        assert host.submit("b", "s", "x", idempotency_key="b").result(timeout=2)["final_response"] == "b:x"
        assert created == [SessionIdentity("a", "s"), SessionIdentity("b", "s")]
    finally:
        host.shutdown()


def test_typed_host_turn_request_preserves_existing_host_behavior():
    created = []

    def factory(identity):
        agent = FakeAgent(identity.session_id, Event())
        created.append(agent)
        return agent

    host = AgentHost(factory, max_sessions=4)
    try:
        request = HostTurnRequest(
            profile="p",
            session_id="s",
            user_message="hello",
            idempotency_key="same",
            conversation_kwargs={"task_id": "task-1"},
        )
        result = host.run_turn(request)
        duplicate = host.submit(request)
        assert result["final_response"] == "s:hello"
        assert duplicate.result(timeout=2)["final_response"] == "s:hello"
        assert created[0].calls == [("hello", {"task_id": "task-1"})]
    finally:
        host.shutdown()
