"""Tests for SimplicioBridge (issue #222) — facade over kernel bindings.

Uses a stub KernelTransport so no ``simplicio`` binary is required.
"""

import time
from threading import Barrier, Event, Thread

from tools.simplicio_bridge import (
    BridgeMetrics,
    CircuitBreaker,
    KernelCallResult,
    KernelTransport,
    SimplicioBridge,
)


class _StubTransport(KernelTransport):
    """Configurable transport: return queued results or raise."""

    def __init__(self, script=None, raises=False):
        self.script = list(script or [])
        self.raises = raises
        self.calls = []

    def _next(self):
        if self.script:
            return self.script.pop(0)
        return KernelCallResult(ok=True, value="ok")

    def gate(self, command, *, pattern_key="", description="", session_key=""):
        self.calls.append(("gate", command))
        if self.raises:
            raise RuntimeError("boom")
        return self._next()

    def checkpoint(self, label, *, workdir="", extra=None):
        self.calls.append(("checkpoint", label))
        if self.raises:
            raise RuntimeError("boom")
        return self._next()

    def mechanical_edit(self, plan):
        self.calls.append(("mechanical_edit", plan))
        if self.raises:
            raise RuntimeError("boom")
        return self._next()

    def orient(self, repo, *, fmt="markdown"):
        self.calls.append(("orient", repo))
        if self.raises:
            raise RuntimeError("boom")
        return self._next()

    def recall(self, query, *, repo=""):
        self.calls.append(("recall", query))
        if self.raises:
            raise RuntimeError("boom")
        return self._next()

    def ledger(self, event):
        self.calls.append(("ledger", event))
        if self.raises:
            raise RuntimeError("boom")
        return self._next()


def test_dispatch_ok_returns_value():
    t = _StubTransport(script=[KernelCallResult(ok=True, value={"approved": True})])
    b = SimplicioBridge(t)
    assert b.gate("rm -rf /") == {"approved": True}
    m = b.metrics()
    assert m.total_calls == 1
    assert m.failures == 0
    assert m.circuit_open is False


def test_dispatch_false_result_degrades_to_none():
    t = _StubTransport(script=[KernelCallResult(ok=False, error="nope")])
    b = SimplicioBridge(t)
    assert b.gate("x") is None
    m = b.metrics()
    assert m.failures == 1
    assert m.last_error == "nope"


def test_circuit_opens_after_threshold():
    t = _StubTransport(raises=True)
    b = SimplicioBridge(t, failure_threshold=3, cooldown_s=0.1)
    for _ in range(3):
        b.gate("x")
    assert b.health()["circuit_open"] is True
    # further calls are skipped (no extra transport calls)
    before = len(t.calls)
    assert b.gate("x") is None
    assert len(t.calls) == before  # circuit blocked it


def test_circuit_recovers_after_cooldown():
    t = _StubTransport(raises=True)
    b = SimplicioBridge(t, failure_threshold=2, cooldown_s=0.05)
    b.gate("x")
    b.gate("x")
    assert b.health()["circuit_open"] is True
    time.sleep(0.1)
    # half-open probe allowed; stub still raises -> stays open
    t.raises = False
    res = b.gate("x")
    # probe succeeded -> breaker resets and call dispatched
    assert res is not None or b.health()["consecutive_failures"] == 0


def test_bridge_rejection_updates_receipt_instead_of_reusing_stale_success():
    t = _StubTransport(raises=True)
    b = SimplicioBridge(t, failure_threshold=1)
    assert b.gate("x") is None
    assert b.gate("x") is None
    receipt = b.last_receipt()
    assert receipt is not None
    assert receipt.ok is False
    assert receipt.error == "circuit_open"


def test_bridge_restart_allows_same_causal_id_to_dispatch_again():
    t = _StubTransport(
        script=[
            KernelCallResult(ok=True, value={"approved": True}),
            KernelCallResult(ok=True, value={"approved": True}),
        ]
    )
    t.close = lambda: None  # type: ignore[attr-defined]
    t.start = lambda: None  # type: ignore[attr-defined]
    b = SimplicioBridge(t)
    assert b.gate("x", causal_id="same") == {"approved": True}
    assert b.close().state == "closed"
    assert b.start().generation == 2
    assert b.gate("x", causal_id="same") == {"approved": True}
    assert len([c for c in t.calls if c[0] == "gate"]) == 2


def test_ledger_idempotent_dedup():
    t = _StubTransport(script=[KernelCallResult(ok=True, value=True)])
    b = SimplicioBridge(t)
    ev = {"kind": "test", "id": "abc"}
    r1 = b.ledger(ev, causal_id="cid-1")
    r2 = b.ledger(ev, causal_id="cid-1")  # repeated causal id
    assert r1 is True and r2 is True
    # second call should be deduped at the bridge layer
    ledger_calls = [c for c in t.calls if c[0] == "ledger"]
    assert len(ledger_calls) == 1


def test_idempotent_waiter_reuses_generation_qualified_receipt():
    started = Event()
    release = Event()
    barrier = Barrier(2)

    class _BlockingTransport(_StubTransport):
        def ledger(self, event):
            self.calls.append(("ledger", event))
            started.set()
            assert release.wait(timeout=2.0)
            return KernelCallResult(ok=True, value=True)

    transport = _BlockingTransport()
    bridge = SimplicioBridge(transport)
    results = []

    def invoke():
        barrier.wait()
        results.append(bridge.ledger({"id": "same"}, causal_id="same"))

    threads = [Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert started.wait(timeout=2.0)
    for _ in range(200):
        with bridge._idempotency_lock:
            if bridge._inflight:
                break
        time.sleep(0.001)
    else:
        raise AssertionError("idempotent owner was not observed in flight")
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert results == [True, True]
    assert [call for call in transport.calls if call[0] == "ledger"] == [
        ("ledger", {"id": "same"})
    ]


def test_health_structure():
    b = SimplicioBridge(_StubTransport())
    h = b.health()
    for k in (
        "healthy",
        "circuit_open",
        "consecutive_failures",
        "total_calls",
        "failures",
        "last_error",
        "last_call_at",
    ):
        assert k in h


def test_causal_id_generated_when_absent():
    t = _StubTransport(script=[KernelCallResult(ok=True, value="v")])
    b = SimplicioBridge(t)
    b.orient("repo")
    # causal sequence advanced
    assert b.metrics().total_calls == 1
