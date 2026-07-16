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
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import logging

from tools.simplicio_transport import SimplicioTransport, TransportReceipt

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


@dataclass(frozen=True)
class BridgeLifecycle:
    """JSON-safe lifecycle state for one bridge binding."""

    state: str
    generation: int
    started_at: Optional[float]
    closed_at: Optional[float] = None
    schema: str = "simplicio-bridge/lifecycle/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "state": self.state,
            "generation": self.generation,
            "started_at": self.started_at,
            "closed_at": self.closed_at,
        }


@dataclass(frozen=True)
class BridgeReadiness:
    """Typed, JSON-safe readiness snapshot for one bridge instance."""

    ready: bool
    state: str
    generation: int
    reason_code: str
    selected_transport: Optional[str] = None
    transport_order: tuple[str, ...] = ("cli", "mcp")
    cli_primary: bool = True
    mcp_fallback_only: bool = True
    transport: dict[str, Any] = field(default_factory=dict)
    schema: str = "simplicio-bridge/readiness/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ready": self.ready,
            "state": self.state,
            "generation": self.generation,
            "reason_code": self.reason_code,
            "selected_transport": self.selected_transport,
            "transport_order": list(self.transport_order),
            "cli_primary": self.cli_primary,
            "mcp_fallback_only": self.mcp_fallback_only,
            "transport": dict(self.transport),
        }


@dataclass(frozen=True)
class BridgeReceipt:
    """Typed evidence for a bridge dispatch, including deduplication."""

    operation: str
    ok: bool
    value: Any = None
    error: Optional[str] = None
    causal_id: Optional[str] = None
    deduplicated: bool = False
    transport: Optional[str] = None
    fallback_reason: Optional[str] = None
    request_id: Optional[str] = None
    schema: str = "simplicio-bridge/receipt/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "operation": self.operation,
            "ok": self.ok,
            "value": self.value,
            "error": self.error,
            "causal_id": self.causal_id,
            "deduplicated": self.deduplicated,
            "transport": self.transport,
            "fallback_reason": self.fallback_reason,
            "request_id": self.request_id,
        }


class KernelTransport(SimplicioTransport):
    """Compatibility name for the default CLI-first transport.

    Older callers imported ``KernelTransport`` from this module.  Keeping it
    as a subclass makes those imports stable while ensuring the default path
    now follows the CLI-first/MCP-fallback contract.
    """


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
    last_transport: Optional[str] = None
    last_fallback_reason: Optional[str] = None
    last_request_id: Optional[str] = None
    last_deduplicated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "failures": self.failures,
            "circuit_open": self.circuit_open,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_call_at": self.last_call_at,
            "last_transport": self.last_transport,
            "last_fallback_reason": self.last_fallback_reason,
            "last_request_id": self.last_request_id,
            "last_deduplicated": self.last_deduplicated,
        }


class SimplicioBridge:
    """Single persistent facade over the kernel bindings.

    Usage::

        bridge = SimplicioBridge()
        decision = bridge.gate("rm -rf /", pattern_key="rm", description="wipe")
        if decision is None:
            # defer to legacy flow
        orient_view = bridge.orient("/path/to/repo")
    """

    def __init__(
        self,
        transport: Optional[KernelTransport] = None,
        *,
        failure_threshold: int = 5,
        cooldown_s: float = 30.0,
        idempotency_max_entries: int = 1024,
    ) -> None:
        if idempotency_max_entries < 1:
            raise ValueError("idempotency_max_entries must be positive")
        self._transport = transport or SimplicioTransport()
        self._breaker = CircuitBreaker(
            failure_threshold=failure_threshold, cooldown_s=cooldown_s
        )
        self._lock = threading.Lock()
        self._metrics = BridgeMetrics()
        self._state = "ready"
        self._generation = 1
        self._started_at: Optional[float] = time.time()
        self._closed_at: Optional[float] = None
        self._idempotency_max_entries = idempotency_max_entries
        # causal id -> receipt, for idempotent callers.  Ordered eviction keeps
        # a long-lived process from retaining every turn forever.
        self._seen: OrderedDict[str, BridgeReceipt] = OrderedDict()
        self._inflight: dict[str, threading.Event] = {}
        self._idempotency_lock = threading.Lock()
        self._last_receipt: Optional[BridgeReceipt] = None
        self._causal_seq = 0

    # -- lifecycle -----------------------------------------------------
    def lifecycle(self) -> BridgeLifecycle:
        with self._lock:
            return BridgeLifecycle(
                state=self._state,
                generation=self._generation,
                started_at=self._started_at,
                closed_at=self._closed_at,
            )

    def start(self) -> BridgeLifecycle:
        """Start (or restart) the lazy bridge; repeated starts are harmless."""
        with self._lock:
            if self._state == "ready":
                return BridgeLifecycle(
                    state=self._state,
                    generation=self._generation,
                    started_at=self._started_at,
                    closed_at=self._closed_at,
                )
            self._state = "ready"
            self._generation += 1
            self._started_at = time.time()
            self._closed_at = None
        start = getattr(self._transport, "start", None)
        if callable(start):
            start()
        return self.lifecycle()

    def close(self) -> BridgeLifecycle:
        """Close the bridge; repeated closes never call the transport twice."""
        with self._lock:
            if self._state == "closed":
                return BridgeLifecycle(
                    state=self._state,
                    generation=self._generation,
                    started_at=self._started_at,
                    closed_at=self._closed_at,
                )
            self._state = "closed"
            self._closed_at = time.time()
            self._breaker.reset()
        close = getattr(self._transport, "close", None)
        if callable(close):
            close()
        return self.lifecycle()

    def __enter__(self) -> "SimplicioBridge":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def last_receipt(self) -> Optional[BridgeReceipt]:
        with self._lock:
            return self._last_receipt

    def readiness(self) -> BridgeReadiness:
        """Return the current lifecycle and transport readiness.

        The snapshot is read-only and does not spawn a process or switch
        transports.  The default transport remains CLI-primary; MCP is
        reported only as an explicit fallback capability.
        """
        lifecycle = self.lifecycle()
        cli_primary = isinstance(self._transport, SimplicioTransport) and hasattr(
            self._transport, "cli_bin"
        )
        compatibility_transport = isinstance(
            self._transport, SimplicioTransport
        ) and not cli_primary
        transport_health: dict[str, Any] = {}
        health_fn = getattr(self._transport, "health", None)
        if callable(health_fn) and not compatibility_transport:
            try:
                candidate = health_fn()
            except Exception as exc:  # defensive for injected transports
                transport_health = {"healthy": False, "detail": str(exc)}
            else:
                if isinstance(candidate, dict):
                    transport_health = dict(candidate)
                else:
                    transport_health = {
                        "healthy": False,
                        "detail": "transport health must be a mapping",
                    }

        # Compatibility doubles may subclass KernelTransport without calling
        # SimplicioTransport.__init__; only a fully initialized transport can
        # make a CLI-primary readiness claim.
        cli_available: Optional[bool] = None
        mcp_configured = False
        if cli_primary:
            cli_bin = getattr(self._transport, "cli_bin", None)
            if not cli_bin:
                resolve_cli = getattr(self._transport, "_resolve_cli", None)
                if callable(resolve_cli):
                    try:
                        cli_bin = resolve_cli()
                    except Exception as exc:  # defensive for custom transports
                        transport_health.setdefault("detail", str(exc))
            cli_available = bool(cli_bin)
            mcp_configured = bool(
                callable(getattr(self._transport, "mcp_call", None))
                or getattr(self._transport, "mcp_command", None)
            )
            transport_health.setdefault("cli_available", cli_available)
            transport_health.setdefault("mcp_configured", mcp_configured)

        selected_transport = transport_health.get("last_transport")
        if selected_transport is None and cli_available:
            selected_transport = "cli"
        elif selected_transport is None and mcp_configured:
            selected_transport = "mcp"

        if lifecycle.state == "closed":
            reason_code = "bridge_closed"
        elif transport_health.get("state") not in (None, "ready"):
            reason_code = "transport_not_ready"
        elif cli_primary and not cli_available and not mcp_configured:
            reason_code = "runtime_unavailable"
        elif transport_health.get("healthy") is False:
            reason_code = "transport_unhealthy"
        elif cli_primary and not cli_available and mcp_configured:
            reason_code = "fallback_ready"
        else:
            reason_code = "ready"

        return BridgeReadiness(
            ready=reason_code in {"ready", "fallback_ready"},
            state=lifecycle.state,
            generation=lifecycle.generation,
            reason_code=reason_code,
            selected_transport=selected_transport,
            cli_primary=cli_primary,
            mcp_fallback_only=cli_primary,
            transport=transport_health,
        )

    def is_ready(self) -> bool:
        """Return whether the bridge can accept a new dispatch."""
        return self.readiness().ready

    # -- causal id -------------------------------------------------------
    def _next_causal_id(self, op: str) -> str:
        with self._lock:
            self._causal_seq += 1
            seq = self._causal_seq
        return f"brg:{op}:{uuid.uuid4().hex[:8]}:{seq}"

    def _idempotency_key(self, causal_id: str) -> str:
        with self._lock:
            generation = self._generation
        return f"{generation}:{causal_id}"

    @staticmethod
    def _failure_receipt(
        op: str, cid: str, error: str, *, request_id: Optional[str] = None
    ) -> BridgeReceipt:
        return BridgeReceipt(
            operation=op,
            ok=False,
            error=error,
            causal_id=cid,
            request_id=request_id or cid,
        )

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
                last_transport=self._metrics.last_transport,
                last_fallback_reason=self._metrics.last_fallback_reason,
                last_request_id=self._metrics.last_request_id,
                last_deduplicated=self._metrics.last_deduplicated,
            )
        return m

    def health(self) -> dict:
        """Structured health snapshot for diagnostics/logging."""
        m = self.metrics()
        result = {
            "schema": "simplicio-bridge/health/v1",
            "healthy": (not m.circuit_open),
            "circuit_open": m.circuit_open,
            "consecutive_failures": m.consecutive_failures,
            "total_calls": m.total_calls,
            "failures": m.failures,
            "last_error": m.last_error,
            "last_call_at": m.last_call_at,
            "last_transport": m.last_transport,
            "last_fallback_reason": m.last_fallback_reason,
            "last_request_id": m.last_request_id,
            "last_deduplicated": m.last_deduplicated,
            "lifecycle": self.lifecycle().to_dict(),
        }
        if result["lifecycle"]["state"] == "closed":
            result["healthy"] = False
        transport_health = getattr(self._transport, "health", None)
        if callable(transport_health):
            try:
                result["transport"] = transport_health()
            except (
                Exception
            ) as exc:  # test doubles/third-party transports may not expose state
                result["transport"] = {"healthy": True, "detail": str(exc)}
        readiness = self.readiness()
        result["readiness"] = readiness.to_dict()
        result["healthy"] = bool(result["healthy"] and readiness.ready)
        return result

    def reset_circuit(self) -> None:
        self._breaker.reset()

    # -- dispatch --------------------------------------------------------
    def _dispatch(
        self,
        op: str,
        fn: Callable[[], KernelCallResult],
        *,
        causal_id: Optional[str] = None,
        idempotent: bool = False,
    ) -> Any:
        cid = causal_id or self._next_causal_id(op)
        idem_key = self._idempotency_key(cid)
        owner = False
        if idempotent:
            with self._idempotency_lock:
                cached = self._seen.get(idem_key)
                if cached is not None:
                    self._seen.move_to_end(idem_key)
                else:
                    cached = None
                if cached is not None:
                    duplicate = BridgeReceipt(
                        operation=op,
                        ok=cached.ok,
                        value=cached.value,
                        error=cached.error,
                        causal_id=cid,
                        deduplicated=True,
                        transport=cached.transport,
                        fallback_reason=cached.fallback_reason,
                        request_id=cached.request_id,
                    )
                else:
                    duplicate = None
                if duplicate is None:
                    event = self._inflight.get(idem_key)
                    if event is None:
                        event = threading.Event()
                        self._inflight[idem_key] = event
                        owner = True
            if duplicate is not None:
                with self._lock:
                    self._metrics.last_deduplicated = True
                    self._last_receipt = duplicate
                return duplicate.value
            if not owner:
                event.wait(timeout=30.0)
                with self._idempotency_lock:
                    cached = self._seen.get(idem_key)
                if cached is None:
                    return None
                with self._lock:
                    self._metrics.last_deduplicated = True
                return cached.value
        with self._lock:
            if self._state == "closed":
                failure = self._failure_receipt(op, cid, "bridge_closed")
                self._metrics.last_error = "bridge_closed"
                self._metrics.last_call_at = time.monotonic()
                self._metrics.last_transport = None
                self._metrics.last_fallback_reason = None
                self._metrics.last_request_id = cid
                self._metrics.last_deduplicated = False
                self._last_receipt = failure
                if owner:
                    with self._idempotency_lock:
                        self._inflight.pop(idem_key, None)
                        event.set()
                return None
        if not self._breaker.allow():
            # circuit open: degrade without hammering the kernel
            with self._lock:
                failure = self._failure_receipt(op, cid, "circuit_open")
                self._metrics.last_error = "circuit_open"
                self._metrics.last_call_at = time.monotonic()
                self._metrics.last_transport = None
                self._metrics.last_fallback_reason = None
                self._metrics.last_request_id = cid
                self._metrics.last_deduplicated = False
                self._last_receipt = failure
            logger.warning("SimplicioBridge: circuit open, skipping %s", op)
            if owner:
                with self._idempotency_lock:
                    self._inflight.pop(idem_key, None)
                    event.set()
            return None
        try:
            res = fn()
        except Exception as exc:  # pragma: no cover - defensive
            res = KernelCallResult(ok=False, error=str(exc))
        with self._lock:
            self._metrics.total_calls += 1
            self._metrics.last_call_at = time.monotonic()
            if isinstance(res, TransportReceipt):
                receipt = res
                value = receipt.value
                ok = receipt.ok
                error = receipt.error.message if receipt.error else None
                self._metrics.last_transport = receipt.transport
                self._metrics.last_fallback_reason = receipt.fallback_reason
                self._metrics.last_request_id = receipt.request_id
            else:
                receipt = None
                value = res.value
                ok = res.ok
                error = res.error
            if ok:
                self._breaker.record_success()
            else:
                self._breaker.record_failure()
                self._metrics.failures += 1
                self._metrics.last_error = error
            self._metrics.last_deduplicated = False
            bridge_receipt = BridgeReceipt(
                operation=op,
                ok=ok,
                value=value,
                error=error,
                causal_id=cid,
                transport=receipt.transport if receipt else None,
                fallback_reason=receipt.fallback_reason if receipt else None,
                request_id=receipt.request_id if receipt else None,
            )
            self._last_receipt = bridge_receipt
        if owner:
            with self._idempotency_lock:
                if ok:
                    self._seen[idem_key] = bridge_receipt
                    self._seen.move_to_end(idem_key)
                    while len(self._seen) > self._idempotency_max_entries:
                        self._seen.popitem(last=False)
                event = self._inflight.pop(idem_key, None)
                if event is not None:
                    event.set()
        if not ok:
            logger.debug("SimplicioBridge.%s failed: %s", op, error)
            return None
        return value

    # -- typed API -------------------------------------------------------
    def gate(
        self,
        command: str,
        *,
        pattern_key: str = "",
        description: str = "",
        session_key: str = "",
        causal_id: Optional[str] = None,
    ) -> Optional[dict]:
        return self._dispatch(
            "gate",
            lambda: self._transport.gate(
                command,
                pattern_key=pattern_key,
                description=description,
                session_key=session_key,
            ),
            causal_id=causal_id,
        )

    def checkpoint(
        self,
        label: str,
        *,
        workdir: str = "",
        extra: Optional[dict] = None,
        causal_id: Optional[str] = None,
    ) -> None:
        self._dispatch(
            "checkpoint",
            lambda: self._transport.checkpoint(label, workdir=workdir, extra=extra),
            causal_id=causal_id,
        )

    def mechanical_edit(
        self, plan: dict, *, causal_id: Optional[str] = None
    ) -> Optional[dict]:
        return self._dispatch(
            "mechanical_edit",
            lambda: self._transport.mechanical_edit(plan),
            causal_id=causal_id,
        )

    def orient(
        self, repo: str, *, fmt: str = "markdown", causal_id: Optional[str] = None
    ) -> Optional[str]:
        return self._dispatch(
            "orient",
            lambda: self._transport.orient(repo, fmt=fmt),
            causal_id=causal_id,
        )

    def recall(
        self, query: str, *, repo: str = "", causal_id: Optional[str] = None
    ) -> Optional[str]:
        return self._dispatch(
            "recall",
            lambda: self._transport.recall(query, repo=repo),
            causal_id=causal_id,
        )

    def ledger(
        self, event: dict, *, idempotent: bool = True, causal_id: Optional[str] = None
    ) -> bool:
        res = self._dispatch(
            "ledger",
            lambda: self._transport.ledger(event),
            causal_id=causal_id,
            idempotent=idempotent,
        )
        return bool(res)
