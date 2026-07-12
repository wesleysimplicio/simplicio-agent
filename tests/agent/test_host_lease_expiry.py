"""Lease expiry, concurrent stress, and shutdown tests for AgentHost.

Complements test_host.py with the coverage required by issue #230:
idle TTL eviction, concurrent multi-session load, and shutdown rejection.
"""

from __future__ import annotations

import time
from concurrent.futures import Future, wait
from threading import Barrier, Event, Thread

import pytest

from agent.host import (
    AgentHost,
    HostBackpressure,
    HostShutdown,
    SessionIdentity,
    SessionPool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SlowAgent:
    """Synthetic agent whose run_conversation blocks until released."""

    def __init__(self, gate: Event | None = None) -> None:
        self.calls: list[str] = []
        self._gate = gate

    def run_conversation(self, message: str, **kwargs: object) -> dict:
        self.calls.append(message)
        if self._gate is not None:
            self._gate.wait(timeout=5)
        return {"final_response": message}


# ---------------------------------------------------------------------------
# Lease expiry (idle_ttl)
# ---------------------------------------------------------------------------


def test_idle_ttl_evicts_expired_sessions():
    """Sessions idle beyond idle_ttl are evicted when the pool is at capacity."""
    pool = SessionPool(
        lambda identity: SlowAgent(),
        max_sessions=2,  # match pool size to session count so eviction fires
        idle_ttl=0.05,   # 50 ms
    )

    # Populate two sessions and release immediately
    id_a = SessionIdentity("p", "a")
    id_b = SessionIdentity("p", "b")
    lease_a = pool.acquire(id_a)
    lease_a.release()
    lease_b = pool.acquire(id_b)
    lease_b.release()

    assert pool.is_present(id_a) and pool.is_present(id_b)

    # Wait for idle TTL to expire
    time.sleep(0.10)

    # Acquiring a new session triggers eviction of expired idle entries
    id_c = SessionIdentity("p", "c")
    lease_c = pool.acquire(id_c)

    # At least one of the expired sessions must have been evicted to make room
    assert not pool.is_present(id_a) or not pool.is_present(id_b)
    assert pool.is_present(id_c)
    lease_c.release()


def test_idle_ttl_does_not_evict_leased_sessions():
    """Even if TTL has passed, a session with active leases is never evicted."""
    pool = SessionPool(
        lambda identity: SlowAgent(),
        max_sessions=2,
        idle_ttl=0.01,  # very short
    )

    id_a = SessionIdentity("p", "leased")
    lease = pool.acquire(id_a)

    time.sleep(0.05)  # well past idle_ttl

    evicted = pool.evict_idle()
    assert id_a not in evicted
    assert pool.is_present(id_a)
    assert pool.is_leased(id_a)

    lease.release()


def test_capacity_backpressure_when_all_sessions_leased():
    """When max_sessions is reached and all are leased, new sessions get HostBackpressure."""
    pool = SessionPool(lambda identity: SlowAgent(), max_sessions=2)

    leases = [
        pool.acquire(SessionIdentity("p", f"s{i}"))
        for i in range(2)
    ]

    with pytest.raises(HostBackpressure, match="saturated"):
        pool.acquire(SessionIdentity("p", "s_overflow"))

    # Release one; now we can acquire a new one
    leases[0].release()
    new_lease = pool.acquire(SessionIdentity("p", "s_new"))
    assert new_lease.agent is not None
    new_lease.release()
    leases[1].release()


# ---------------------------------------------------------------------------
# Concurrent stress
# ---------------------------------------------------------------------------


def test_concurrent_multi_session_submissions():
    """Submit turns across many sessions concurrently and verify all complete."""
    results: dict[str, Future] = {}
    host = AgentHost(lambda identity: SlowAgent(), max_sessions=16, max_workers=8, max_pending=64)
    try:
        for i in range(16):
            results[f"s{i}"] = host.submit("p", f"s{i}", f"msg-{i}", idempotency_key=f"key-{i}")

        for sid, future in results.items():
            result = future.result(timeout=10)
            assert result["final_response"].startswith("msg-")
    finally:
        host.shutdown()


def test_concurrent_same_session_serializes():
    """Multiple concurrent turns on the same session must serialize (not interleave)."""
    gate = Event()
    order: list[tuple[str, str]] = []

    class OrderTracker:
        def run_conversation(self, message: str, **kwargs: object) -> dict:
            order.append(("start", message))
            # Small sleep to ensure overlap would be detectable
            time.sleep(0.02)
            order.append(("end", message))
            return {"final_response": message}

    host = AgentHost(lambda identity: OrderTracker(), max_sessions=4, max_workers=4)
    try:
        futures = [
            host.submit("p", "same", f"turn-{i}", idempotency_key=f"turn-{i}")
            for i in range(4)
        ]
        for f in futures:
            f.result(timeout=10)

        # Verify serialization: each "start" is immediately followed by its own "end"
        for i in range(0, len(order), 2):
            assert order[i][0] == "start"
            assert order[i + 1][0] == "end"
            assert order[i][1] == order[i + 1][1]
    finally:
        host.shutdown()


def test_concurrent_pool_acquire_release_stress():
    """Hammer acquire/release from multiple threads to surface race conditions."""
    pool = SessionPool(lambda identity: SlowAgent(), max_sessions=8, idle_ttl=0.05)

    errors: list[Exception] = []
    barrier = Barrier(8)

    def worker(thread_id: int) -> None:
        try:
            barrier.wait(timeout=5)
            for cycle in range(10):
                sid = SessionIdentity("p", f"t{thread_id}-{cycle % 4}")
                try:
                    lease = pool.acquire(sid)
                    time.sleep(0.005)
                    lease.release()
                except HostBackpressure:
                    pass  # expected under contention
        except Exception as exc:
            errors.append(exc)

    threads = [Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == [], f"Unexpected errors in concurrent stress: {errors}"


# ---------------------------------------------------------------------------
# Shutdown rejection
# ---------------------------------------------------------------------------


def test_shutdown_rejects_new_submissions():
    """After shutdown(), submitting a new turn raises HostShutdown."""
    host = AgentHost(lambda identity: SlowAgent(), max_sessions=4)
    host.shutdown()

    with pytest.raises(HostShutdown, match="draining"):
        host.submit("p", "s", "too late")


def test_in_flight_turn_completes_after_shutdown():
    """A turn already in progress must still complete even after shutdown is called."""
    gate = Event()
    host = AgentHost(lambda identity: SlowAgent(gate), max_sessions=4)
    try:
        future = host.submit("p", "s", "in-flight", idempotency_key="inflight")
        # Let the turn start executing
        time.sleep(0.1)
        host.shutdown(wait=False)
        gate.set()
        result = future.result(timeout=5)
        assert result["final_response"] == "in-flight"
    except Exception:
        gate.set()
        raise


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def test_recover_leased_session_raises_backpressure():
    """Recovering a session that has active leases must raise HostBackpressure."""
    gate = Event()
    host = AgentHost(lambda identity: SlowAgent(gate), max_sessions=4)
    try:
        future = host.submit("p", "s", "busy", idempotency_key="busy")
        # Let the turn start
        time.sleep(0.1)

        with pytest.raises(HostBackpressure, match="cannot recover"):
            host.pool.recover(SessionIdentity("p", "s"))

        gate.set()
        future.result(timeout=5)
    except Exception:
        gate.set()
        raise
    finally:
        host.shutdown()


def test_recover_nonexistent_session_returns_false():
    """Recovering a session that doesn't exist in the pool returns False."""
    host = AgentHost(lambda identity: SlowAgent(), max_sessions=4)
    try:
        assert host.recover("p", "nonexistent") is False
    finally:
        host.shutdown()


def test_lease_context_manager_releases_on_exception():
    """SessionLease used as a context manager releases even when the body raises."""
    pool = SessionPool(lambda identity: SlowAgent(), max_sessions=2)
    sid = SessionIdentity("p", "ctx")

    with pytest.raises(ValueError, match="boom"):
        with pool.acquire(sid) as lease:
            assert pool.is_leased(sid)
            raise ValueError("boom")

    # After the exception, the lease should be released
    assert not pool.is_leased(sid)
    assert pool.is_present(sid)
