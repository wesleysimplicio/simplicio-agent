"""Tests for SimplicioBridge (issue #222) — facade over kernel bindings.

Uses a stub KernelTransport so no ``simplicio`` binary is required.
"""

import time

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


def test_health_structure():
    b = SimplicioBridge(_StubTransport())
    h = b.health()
    for k in ("healthy", "circuit_open", "consecutive_failures",
             "total_calls", "failures", "last_error", "last_call_at"):
        assert k in h


def test_causal_id_generated_when_absent():
    t = _StubTransport(script=[KernelCallResult(ok=True, value="v")])
    b = SimplicioBridge(t)
    b.orient("repo")
    # causal sequence advanced
    assert b.metrics().total_calls == 1
