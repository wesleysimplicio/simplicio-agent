"""Contract tests for the embedded AgentHost vertical slice."""

from concurrent.futures import CancelledError, wait
from threading import Event

import pytest

from agent.host import AgentHost, HostBackpressure, SessionIdentity
from agent.protocol import HostTurnRequest
from agent.session import (
    AgentSession,
    SessionIdentity as SessionBoundaryIdentity,
    SessionSnapshot,
)
from agent.turn_engine import TurnPhase


class RecordingSession:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def begin_turn(self, *, turn_id=None, attempt_id="0"):
        context = (turn_id, attempt_id)
        self.events.append(("begin", context))
        return context

    def complete_turn(self, context):
        self.events.append(("complete", context))

    def fail_turn(self, context):
        self.events.append(("fail", context))

    def close(self):
        self.closed = True
        self.events.append(("close", None))


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


def test_cancel_turn_cancels_only_a_queued_correlated_turn():
    gate = Event()
    started = Event()
    host = AgentHost(
        lambda identity: FakeAgent(identity.session_id, started, gate),
        max_workers=1,
    )
    try:
        running = host.submit("p", "s", "running", turn_id="running")
        assert started.wait(timeout=1)
        assert host.cancel_turn("running", profile="p", session_id="s") == "running"
        queued = host.submit("p", "s", "queued", turn_id="queued")
        assert host.cancel_turn("queued", profile="p", session_id="s") == "cancelled"
        with pytest.raises(CancelledError):
            queued.result(timeout=1)
        assert (
            host.reconcile_turn("queued", profile="p", session_id="s")["state"]
            == "terminal"
        )
        gate.set()
        result = running.result(timeout=2)
        receipt = host.reconcile_turn("running", profile="p", session_id="s")
        assert receipt == {"state": "terminal", "result": result}
    finally:
        gate.set()
        host.shutdown()


def test_correlated_turn_operations_fail_closed_on_identity_mismatch():
    gate = Event()
    started = Event()
    host = AgentHost(lambda identity: FakeAgent(identity.session_id, started, gate))
    try:
        future = host.submit(
            "p", "s", "running", turn_id="turn-1", incarnation="inc-1", revision=2
        )
        assert started.wait(timeout=1)
        with pytest.raises(ValueError, match="identity"):
            host.cancel_turn("turn-1", profile="p", session_id="other")
        with pytest.raises(ValueError, match="identity"):
            host.reconcile_turn(
                "turn-1", profile="p", session_id="s", incarnation="inc-1", revision=3
            )
        assert host.reconcile_turn(
            "turn-1", profile="p", session_id="s", incarnation="inc-1", revision=2
        )["state"] == "running"
        gate.set()
        future.result(timeout=2)
    finally:
        gate.set()
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


def test_idempotency_cache_is_discarded_on_session_eviction_not_host_lifetime():
    """Regression guard for an unbounded-growth bug: the idempotency cache
    used to live on the ``AgentHost`` itself, keyed by every distinct
    ``(identity, idempotency_key)`` pair ever submitted, and nothing ever
    removed entries from it. A long-running warm host (this issue's whole
    point) would accumulate one entry per turn forever, growing RSS without
    bound over a soak — directly contradicting the "RSS estabiliza" /
    eviction acceptance criteria for AgentHost.

    The cache must instead be scoped to the per-session pool entry so it is
    discarded automatically the moment the idle session is evicted.
    """
    host = AgentHost(lambda identity: FakeAgent(identity.session_id, Event()), max_sessions=1)
    try:
        host.submit("p", "s", "one", idempotency_key="k1").result(timeout=2)
        entry = host.pool._entries[SessionIdentity("p", "s")]
        assert "k1" in entry.idempotent

        # A second, unrelated session forces the idle "s" entry (and its
        # idempotency cache) out of the size-bounded pool.
        host.submit("p", "other", "x", idempotency_key="k2").result(timeout=2)
        assert not host.pool.is_present(SessionIdentity("p", "s"))

        # Resubmitting the same idempotency key after eviction must run a
        # fresh turn (the old cache entry is gone with the evicted entry),
        # not resurrect a stale cached future from a dict that outlives
        # sessions.
        result = host.submit("p", "s", "two", idempotency_key="k1").result(timeout=2)
        assert result["final_response"] == "s:two"
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


def test_host_turn_request_does_not_forward_transport_fencing_metadata():
    request = HostTurnRequest.from_mapping(
        {
            "session_id": "session-a",
            "message": "hello",
            "host_instance_id": "process-incarnation-000001",
        },
        default_profile="desktop",
    )

    assert "host_instance_id" not in request.conversation_kwargs


def test_session_lifecycle_wraps_turn_with_correlation_ids_and_closes_on_eviction():
    events = []
    sessions = []

    def make_session(_identity):
        session = RecordingSession(events)
        sessions.append(session)
        return session

    host = AgentHost(
        lambda identity: FakeAgent(identity.session_id, Event()),
        max_sessions=1,
        session_factory=make_session,
    )
    try:
        result = host.run_turn(
            "p",
            "s",
            "hello",
            turn_id="turn-7",
            attempt_id="attempt-3",
        )
        assert result["final_response"] == "s:hello"
        assert events[:2] == [
            ("begin", ("turn-7", "attempt-3")),
            ("complete", ("turn-7", "attempt-3")),
        ]
        assert host.recover("p", "s") is True
        assert events[-1] == ("close", None)
        assert sessions[0].closed
    finally:
        host.shutdown()


def test_session_lifecycle_marks_failed_turn_and_releases_it():
    events = []

    class FailingAgent(FakeAgent):
        def run_conversation(self, message, **kwargs):
            raise RuntimeError("boom")

    host = AgentHost(
        lambda identity: FailingAgent(identity.session_id, Event()),
        session_factory=lambda _identity: RecordingSession(events),
    )
    try:
        with pytest.raises(RuntimeError, match="boom"):
            host.run_turn(
                "p",
                "s",
                "hello",
                turn_id="turn-fail",
                attempt_id="attempt-1",
            )
        assert [event[0] for event in events] == ["begin", "fail"]
        assert host.pool.is_leased(SessionIdentity("p", "s")) is False
    finally:
        host.shutdown()


def test_agent_session_is_a_real_host_lifecycle_boundary():
    sessions = []

    class SessionAwareAgent(FakeAgent):
        def run_conversation(self, message, **kwargs):
            from agent.conversation_loop import _finish_turn_engine, _start_turn_engine

            self.adopted_context = _start_turn_engine(
                turn_id="loop-local-id",
                session_id=self.name,
                agent=self,
            )
            self.adopted_history = tuple(self.adopted_context.history)
            _finish_turn_engine(self, {"completed": True}, failed=False)
            return super().run_conversation(message, **kwargs)

    def make_session(identity):
        snapshot = SessionSnapshot(
            SessionBoundaryIdentity(
                identity.profile,
                identity.session_id,
                identity.incarnation,
                identity.revision,
            ),
            "prompt-hash",
            "toolset-hash",
            "provider-route",
        )
        session = AgentSession(snapshot)
        sessions.append(session)
        return session

    agents = []

    def make_agent(identity):
        agent = SessionAwareAgent(identity.session_id, Event())
        agents.append(agent)
        return agent

    host = AgentHost(
        make_agent,
        session_factory=make_session,
    )
    try:
        host.run_turn("p", "s", "hello", turn_id="turn-real")
        assert sessions[0].active_turns == 0
        assert not sessions[0].closed
        assert agents[0].adopted_history == (TurnPhase.ACCEPTED,)
        assert agents[0].adopted_context.phase is TurnPhase.COMPLETED
    finally:
        host.shutdown()
