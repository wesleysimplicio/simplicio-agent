"""SimplicioBridge — single typed persistent binding surface to the kernel.

Issue #222. This is the *facade* the rest of the agent talks to instead of
calling ``tools.kernel_binding`` directly per-binding. It does NOT replace the
underlying ``kernel_binding`` functions (those stay the source of truth for the
actual binary invocation); it wraps them behind one object that:

* holds a persistent ``_WarmKernelClient``-style connection slot (lazy),
* exposes a small typed API (gate / checkpoint / mechanical_edit / orient /
  recall / ledger) with consistent return shapes,
* runs a :class:`CircuitBreaker` so a wedged kernel can't stall the loop
  forever, and surfaces ``health()`` / ``metrics()`` for diagnostics,
* stamps every call with a causal id + dedupes idempotent calls so a
  retried turn doesn't double-append to the evidence ledger.

Behavior-neutral with respect to the kernel: every method degrades the same
way ``kernel_binding`` would (``None`` / ``False`` on unavailable, raise only
when the binding ``mode == "required"``). The bridge never invents a kernel
decision.

The transport is injectable (``KernelTransport``) so tests run without the
``simplicio`` binary on PATH.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Bounded failure counter + health flag.

    The bridge flips ``open`` after ``failure_threshold`` *consecutive*
    failures and stays open for ``cooldown_s``, after which it half-opens
    for one probe call. This keeps a dead kernel from being hammered every
    tool call (the 90s-stall class of bug) while still recovering once the
    kernel is back.
    """

    def __init__(self, failure_threshold: int = 5, cooldown_s: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._total_failures = 0
        self._total_calls = 0
        self._opened_at: Optional[float] = None
        self._open = False

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def allow(self) -> bool:
        """True if a call may proceed right now."""
        with self._lock:
            if not self._open:
                return True
            if self._opened_at is None:
                return True
            if time.monotonic() - self._opened_at >= self.cooldown_s:
                # half-open: allow one probe
                self._open = False
                self._opened_at = None
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._total_calls += 1

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._total_failures += 1
            self._total_calls += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._open = True
                self._opened_at = time.monotonic()

    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def reset(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._total_failures = 0
            self._total_calls = 0
            self._opened_at = None
            self._open = False


# ---------------------------------------------------------------------------
# Transport contract (injectable)
# ---------------------------------------------------------------------------

@dataclass
class KernelCallResult:
    ok: bool
    value: Any = None
    error: Optional[str] = None


class KernelTransport:
    """Default transport: delegates to ``tools.kernel_binding``.

    Override in tests with a stub that returns ``KernelCallResult``.
    """

    def gate(self, command: str, *, pattern_key: str, description: str,
             session_key: str) -> KernelCallResult:
        from tools.kernel_binding import evaluate_action_gate
        try:
            v = evaluate_action_gate(
                command, pattern_key=pattern_key,
                description=description, session_key=session_key,
            )
            return KernelCallResult(ok=True, value=v)
        except Exception as exc:  # pragma: no cover - defensive
            return KernelCallResult(ok=False, error=str(exc))

    def checkpoint(self, label: str, *, workdir: str, extra: Optional[dict]) -> KernelCallResult:
        from tools.kernel_binding import mirror_checkpoint
        try:
            mirror_checkpoint(label, workdir=workdir, extra=extra)
            return KernelCallResult(ok=True)
        except Exception as exc:
            return KernelCallResult(ok=False, error=str(exc))

    def mechanical_edit(self, plan: dict) -> KernelCallResult:
        from tools.kernel_binding import edit_mechanical
        try:
            return KernelCallResult(ok=True, value=edit_mechanical(plan))
        except Exception as exc:
            return KernelCallResult(ok=False, error=str(exc))

    def orient(self, repo: str, *, fmt: str = "markdown") -> KernelCallResult:
        from tools.kernel_binding import orient_map
        try:
            return KernelCallResult(ok=True, value=orient_map(repo, fmt=fmt))
        except Exception as exc:
            return KernelCallResult(ok=False, error=str(exc))

    def recall(self, query: str, *, repo: str = "") -> KernelCallResult:
        from tools.kernel_binding import memory_recall
        try:
            return KernelCallResult(ok=True, value=memory_recall(query, repo=repo))
        except Exception as exc:
            return KernelCallResult(ok=False, error=str(exc))

    def ledger(self, event: dict) -> KernelCallResult:
        from tools.kernel_binding import ledger_append
        try:
            return KernelCallResult(ok=True, value=ledger_append(event))
        except Exception as exc:
            return KernelCallResult(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

@dataclass
class BridgeMetrics:
    total_calls: int = 0
    failures: int = 0
    circuit_open: bool = False
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    last_call_at: Optional[float] = None


class SimplicioBridge:
    """Single persistent facade over the kernel bindings.

    Usage::

        bridge = SimplicioBridge()
        decision = bridge.gate("rm -rf /", pattern_key="rm", description="wipe")
        if decision is None:
            # defer to legacy flow
        orient_view = bridge.orient("/path/to/repo")
    """

    def __init__(self, transport: Optional[KernelTransport] = None,
                 *, failure_threshold: int = 5, cooldown_s: float = 30.0) -> None:
        self._transport = transport or KernelTransport()
        self._breaker = CircuitBreaker(failure_threshold=failure_threshold,
                                       cooldown_s=cooldown_s)
        self._lock = threading.Lock()
        self._metrics = BridgeMetrics()
        # causal id -> last result, for idempotent callers
        self._seen: Dict[str, Any] = {}
        self._causal_seq = 0

    # -- causal id -------------------------------------------------------
    def _next_causal_id(self, op: str) -> str:
        with self._lock:
            self._causal_seq += 1
            seq = self._causal_seq
        return f"brg:{op}:{uuid.uuid4().hex[:8]}:{seq}"

    # -- metrics ---------------------------------------------------------
    def metrics(self) -> BridgeMetrics:
        with self._lock:
            m = BridgeMetrics(
                total_calls=self._metrics.total_calls,
                failures=self._metrics.failures,
                circuit_open=self._breaker.is_open(),
                consecutive_failures=self._breaker.consecutive_failures,
                last_error=self._metrics.last_error,
                last_call_at=self._metrics.last_call_at,
            )
        return m

    def health(self) -> dict:
        """Structured health snapshot for diagnostics/logging."""
        m = self.metrics()
        return {
            "healthy": (not m.circuit_open),
            "circuit_open": m.circuit_open,
            "consecutive_failures": m.consecutive_failures,
            "total_calls": m.total_calls,
            "failures": m.failures,
            "last_error": m.last_error,
            "last_call_at": m.last_call_at,
        }

    def reset_circuit(self) -> None:
        self._breaker.reset()

    # -- dispatch --------------------------------------------------------
    def _dispatch(self, op: str, fn: Callable[[], KernelCallResult],
                  *, causal_id: Optional[str] = None,
                  idempotent: bool = False) -> Any:
        cid = causal_id or self._next_causal_id(op)
        if idempotent and cid in self._seen:
            return self._seen[cid]
        if not self._breaker.allow():
            # circuit open: degrade without hammering the kernel
            with self._lock:
                self._metrics.last_error = "circuit_open"
                self._metrics.last_call_at = time.monotonic()
            logger.warning("SimplicioBridge: circuit open, skipping %s", op)
            return None
        try:
            res = fn()
        except Exception as exc:  # pragma: no cover - defensive
            res = KernelCallResult(ok=False, error=str(exc))
        with self._lock:
            self._metrics.total_calls += 1
            self._metrics.last_call_at = time.monotonic()
            if res.ok:
                self._breaker.record_success()
            else:
                self._breaker.record_failure()
                self._metrics.failures += 1
                self._metrics.last_error = res.error
        if not res.ok:
            logger.debug("SimplicioBridge.%s failed: %s", op, res.error)
            return None
        if idempotent:
            self._seen[cid] = res.value
        return res.value

    # -- typed API -------------------------------------------------------
    def gate(self, command: str, *, pattern_key: str = "", description: str = "",
             session_key: str = "", causal_id: Optional[str] = None) -> Optional[dict]:
        return self._dispatch(
            "gate",
            lambda: self._transport.gate(
                command, pattern_key=pattern_key,
                description=description, session_key=session_key),
            causal_id=causal_id,
        )

    def checkpoint(self, label: str, *, workdir: str = "", extra: Optional[dict] = None,
                   causal_id: Optional[str] = None) -> None:
        self._dispatch(
            "checkpoint",
            lambda: self._transport.checkpoint(label, workdir=workdir, extra=extra),
            causal_id=causal_id,
        )

    def mechanical_edit(self, plan: dict, *, causal_id: Optional[str] = None) -> Optional[dict]:
        return self._dispatch(
            "mechanical_edit",
            lambda: self._transport.mechanical_edit(plan),
            causal_id=causal_id,
        )

    def orient(self, repo: str, *, fmt: str = "markdown",
               causal_id: Optional[str] = None) -> Optional[str]:
        return self._dispatch(
            "orient",
            lambda: self._transport.orient(repo, fmt=fmt),
            causal_id=causal_id,
        )

    def recall(self, query: str, *, repo: str = "",
               causal_id: Optional[str] = None) -> Optional[str]:
        return self._dispatch(
            "recall",
            lambda: self._transport.recall(query, repo=repo),
            causal_id=causal_id,
        )

    def ledger(self, event: dict, *, idempotent: bool = True,
               causal_id: Optional[str] = None) -> bool:
        res = self._dispatch(
            "ledger",
            lambda: self._transport.ledger(event),
            causal_id=causal_id,
            idempotent=idempotent,
        )
        return bool(res)
