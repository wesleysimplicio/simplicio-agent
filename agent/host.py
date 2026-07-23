"""Embedded AgentHost: durable session identity, pooling, and turn scheduling.

The host is deliberately an adapter around ``AIAgent`` rather than a second
agent implementation.  A surface supplies an ``agent_factory`` and every turn
still runs through the existing ``AIAgent.run_conversation`` contract.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import asyncio
from threading import Lock
import time
from typing import Any, Callable, Optional, overload

from .protocol import (
    AgentConversationResult,
    AgentProtocol,
    AgentSessionProtocol,
    HostStatusSnapshot,
    HostTurnRequest,
    SessionSnapshot,
)

class HostBackpressure(RuntimeError):
    """The host cannot admit another leased session or queued turn."""


class HostShutdown(RuntimeError):
    """A turn was submitted after the host began draining."""


@dataclass(frozen=True)
class SessionIdentity:
    """Stable routing identity for one in-process session incarnation."""

    profile: str
    session_id: str
    incarnation: str = "default"
    revision: int = 0


@dataclass
class _SessionEntry:
    identity: SessionIdentity
    agent: AgentProtocol
    session: AgentSessionProtocol | None = None
    turn_lock: Lock = field(default_factory=Lock)
    active_leases: int = 0
    last_used: float = field(default_factory=time.monotonic)
    # Idempotency cache is scoped to this entry (not the host-wide process
    # lifetime) so it is discarded automatically when the session is evicted
    # from the pool, instead of growing without bound for the life of a
    # long-running warm host.
    idempotent: dict[str, "Future[Any]"] = field(default_factory=dict)
    async_idempotent: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    idempotent_lock: Lock = field(default_factory=Lock)


@dataclass(frozen=True)
class _CorrelatedTurn:
    identity: SessionIdentity
    future: Future[AgentConversationResult]


class SessionDirectory:
    """Resolve surface identity into a profile-isolated session identity."""

    def resolve(
        self,
        profile: str,
        session_id: str,
        *,
        incarnation: str = "default",
        revision: int = 0,
    ) -> SessionIdentity:
        if not profile or not session_id:
            raise ValueError("profile and session_id are required")
        return SessionIdentity(profile, session_id, incarnation, revision)


class SessionLease:
    def __init__(self, pool: "SessionPool", entry: _SessionEntry) -> None:
        self._pool = pool
        self.entry = entry
        self._released = False

    @property
    def agent(self) -> AgentProtocol:
        return self.entry.agent

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._pool.release(self)

    def __enter__(self) -> "SessionLease":
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class SessionPool:
    """Bounded LRU pool whose active leases are never evicted."""

    def __init__(
        self,
        agent_factory: Callable[[SessionIdentity], AgentProtocol],
        *,
        max_sessions: int = 32,
        idle_ttl: Optional[float] = None,
        session_factory: Optional[Callable[[SessionIdentity], AgentSessionProtocol]] = None,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self._factory = agent_factory
        self.max_sessions = max_sessions
        self.idle_ttl = idle_ttl
        self._session_factory = session_factory
        self._entries: "OrderedDict[SessionIdentity, _SessionEntry]" = OrderedDict()
        self._lock = Lock()

    def acquire(self, identity: SessionIdentity) -> SessionLease:
        with self._lock:
            entry = self._entries.get(identity)
            if entry is None:
                self._evict_locked()
                if len(self._entries) >= self.max_sessions:
                    raise HostBackpressure("session pool is saturated; retry later")
                session = (
                    self._session_factory(identity)
                    if self._session_factory is not None
                    else None
                )
                entry = _SessionEntry(identity, self._factory(identity), session)
                self._entries[identity] = entry
            entry.active_leases += 1
            entry.last_used = time.monotonic()
            self._entries.move_to_end(identity)
            return SessionLease(self, entry)

    def release(self, lease: SessionLease) -> None:
        with self._lock:
            entry = lease.entry
            entry.active_leases = max(0, entry.active_leases - 1)
            entry.last_used = time.monotonic()
            self._entries.move_to_end(entry.identity)

    def _evict_locked(self) -> None:
        now = time.monotonic()
        for identity, entry in list(self._entries.items()):
            expired = (
                self.idle_ttl is not None and now - entry.last_used >= self.idle_ttl
            )
            if entry.active_leases == 0 and (
                expired or len(self._entries) >= self.max_sessions
            ):
                if entry.session is not None:
                    entry.session.close()
                self._entries.pop(identity)
                if len(self._entries) < self.max_sessions:
                    break

    def evict_idle(self) -> list[SessionIdentity]:
        with self._lock:
            before = set(self._entries)
            self._evict_locked()
            return [identity for identity in before if identity not in self._entries]

    def is_leased(self, identity: SessionIdentity) -> bool:
        with self._lock:
            entry = self._entries.get(identity)
            return bool(entry and entry.active_leases)

    def is_present(self, identity: SessionIdentity) -> bool:
        with self._lock:
            return identity in self._entries

    def recover(self, identity: SessionIdentity) -> bool:
        """Discard an idle in-memory agent so the next turn rebuilds it.

        SessionDB remains canonical; this only repairs a poisoned process-local
        resource after a provider/client failure.
        """
        with self._lock:
            entry = self._entries.get(identity)
            if entry is None:
                return False
            if entry.active_leases:
                raise HostBackpressure("cannot recover a leased session")
            if entry.session is not None:
                entry.session.close()
            self._entries.pop(identity)
            return True

    def snapshot(self) -> list[SessionSnapshot]:
        with self._lock:
            return [
                {
                    "profile": e.identity.profile,
                    "session_id": e.identity.session_id,
                    "incarnation": e.identity.incarnation,
                    "revision": e.identity.revision,
                    "active_leases": e.active_leases,
                }
                for e in self._entries.values()
            ]


class TurnScheduler:
    """Global bounded executor plus one writer lock per session."""

    def __init__(self, max_workers: int = 4, max_pending: int = 64) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="agent-turn"
        )
        self.max_pending = max_pending
        self._lock = Lock()
        self._pending = 0

    def submit(self, entry: _SessionEntry, fn: Callable[[], Any]) -> Future[Any]:
        with self._lock:
            if self._pending >= self.max_pending:
                raise HostBackpressure("turn queue is saturated; retry later")
            self._pending += 1

        def run() -> Any:
            try:
                with entry.turn_lock:
                    return fn()
            finally:
                with self._lock:
                    self._pending -= 1

        try:
            return self._executor.submit(run)
        except BaseException:
            with self._lock:
                self._pending -= 1
            raise

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


class AgentHost:
    """Small end-to-end host usable by CLI, gateway, TUI, or embedded callers."""

    def __init__(
        self,
        agent_factory: Callable[[SessionIdentity], AgentProtocol],
        *,
        max_sessions: int = 32,
        max_workers: int = 4,
        max_pending: int = 64,
        directory: Optional[SessionDirectory] = None,
        session_factory: Optional[Callable[[SessionIdentity], AgentSessionProtocol]] = None,
    ) -> None:
        self.directory = directory or SessionDirectory()
        self.pool = SessionPool(
            agent_factory,
            max_sessions=max_sessions,
            session_factory=session_factory,
        )
        self.scheduler = TurnScheduler(max_workers=max_workers, max_pending=max_pending)
        self._lock = Lock()
        self._stopping = False
        # Only explicitly correlated turns are addressable for cancellation.
        # A running provider call cannot be truthfully reported as cancelled;
        # callers receive ``running`` and must reconcile its terminal receipt.
        self._turns: "OrderedDict[str, _CorrelatedTurn]" = OrderedDict()
        self._turns_lock = Lock()
        self._max_tracked_turns = max_pending + max_workers

    def _track_turn(
        self,
        request: HostTurnRequest,
        future: Future[AgentConversationResult],
    ) -> Future[AgentConversationResult]:
        if request.turn_id is None:
            return future
        identity = self.directory.resolve(
            request.profile,
            request.session_id,
            incarnation=request.incarnation,
            revision=request.revision,
        )
        with self._turns_lock:
            if request.turn_id in self._turns:
                raise ValueError("turn_id is already tracked")
            # Retain terminal receipts for reconciliation, but bound them. A
            # running turn is never evicted merely to make room for a receipt.
            while len(self._turns) >= self._max_tracked_turns:
                terminal_id = next(
                    (key for key, turn in self._turns.items() if turn.future.done()),
                    None,
                )
                if terminal_id is None:
                    raise HostBackpressure(
                        "correlated turn ledger is saturated; retry later"
                    )
                self._turns.pop(terminal_id)
            self._turns[request.turn_id] = _CorrelatedTurn(identity, future)
        return future

    def _correlated_turn(
        self,
        turn_id: str,
        *,
        profile: str,
        session_id: str,
        incarnation: str = "default",
        revision: int = 0,
    ) -> _CorrelatedTurn | None:
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise ValueError("turn_id must be non-empty")
        expected = self.directory.resolve(
            profile, session_id, incarnation=incarnation, revision=revision
        )
        with self._turns_lock:
            turn = self._turns.get(turn_id)
        if turn is not None and turn.identity != expected:
            raise ValueError("turn identity does not match the correlated request")
        return turn

    def cancel_turn(
        self,
        turn_id: str,
        *,
        profile: str,
        session_id: str,
        incarnation: str = "default",
        revision: int = 0,
    ) -> str:
        """Cancel a queued correlated turn without misreporting a running one.

        Returns one of ``cancelled``, ``running``, ``terminal`` or
        ``not_found``. ``running`` is deliberately non-terminal: an in-flight
        provider/tool operation must be reconciled through its final receipt,
        never retried as if cancellation had succeeded.
        """
        turn = self._correlated_turn(
            turn_id,
            profile=profile,
            session_id=session_id,
            incarnation=incarnation,
            revision=revision,
        )
        if turn is None:
            return "not_found"
        future = turn.future
        if future.cancel():
            return "cancelled"
        if future.done():
            return "terminal"
        return "running"

    def reconcile_turn(
        self,
        turn_id: str,
        *,
        profile: str,
        session_id: str,
        incarnation: str = "default",
        revision: int = 0,
    ) -> dict[str, Any]:
        """Return an authoritative correlated-turn receipt without effects."""
        turn = self._correlated_turn(
            turn_id,
            profile=profile,
            session_id=session_id,
            incarnation=incarnation,
            revision=revision,
        )
        if turn is None:
            return {"state": "not_found"}
        future = turn.future
        if not future.done():
            return {"state": "running"}
        if future.cancelled():
            return {"state": "terminal", "outcome": "cancelled"}
        error = future.exception()
        if error is not None:
            return {
                "state": "terminal",
                "outcome": "failed",
                "error": type(error).__name__,
            }
        return {"state": "terminal", "result": future.result()}

    @staticmethod
    def _coerce_turn_request(
        profile: str | HostTurnRequest,
        session_id: str | None = None,
        user_message: str | None = None,
        *,
        idempotency_key: Optional[str] = None,
        turn_id: Optional[str] = None,
        attempt_id: str = "0",
        incarnation: str = "default",
        revision: int = 0,
        **conversation_kwargs: Any,
    ) -> HostTurnRequest:
        if isinstance(profile, HostTurnRequest):
            return profile
        if session_id is None or user_message is None:
            raise TypeError("session_id and user_message are required")
        return HostTurnRequest(
            profile=profile,
            session_id=session_id,
            user_message=user_message,
            idempotency_key=idempotency_key,
            turn_id=turn_id,
            attempt_id=attempt_id,
            incarnation=incarnation,
            revision=revision,
            conversation_kwargs=conversation_kwargs,
        )

    @overload
    def submit(
        self,
        profile: HostTurnRequest,
    ) -> Future[AgentConversationResult]: ...

    @overload
    def submit(
        self,
        profile: str,
        session_id: str,
        user_message: str,
        *,
        idempotency_key: Optional[str] = None,
        turn_id: Optional[str] = None,
        attempt_id: str = "0",
        incarnation: str = "default",
        revision: int = 0,
        **conversation_kwargs: Any,
    ) -> Future[AgentConversationResult]: ...

    def submit(
        self,
        profile: str | HostTurnRequest,
        session_id: str | None = None,
        user_message: str | None = None,
        *,
        idempotency_key: Optional[str] = None,
        turn_id: Optional[str] = None,
        attempt_id: str = "0",
        incarnation: str = "default",
        revision: int = 0,
        **conversation_kwargs: Any,
    ) -> Future[AgentConversationResult]:
        request = self._coerce_turn_request(
            profile,
            session_id,
            user_message,
            idempotency_key=idempotency_key,
            turn_id=turn_id,
            attempt_id=attempt_id,
            incarnation=incarnation,
            revision=revision,
            **conversation_kwargs,
        )
        identity = self.directory.resolve(
            request.profile,
            request.session_id,
            incarnation=request.incarnation,
            revision=request.revision,
        )
        key = request.idempotency_key
        with self._lock:
            if self._stopping:
                raise HostShutdown("agent host is draining")

        lease = self.pool.acquire(identity)
        entry = lease.entry

        def release(done: Future[Any]) -> None:
            lease.release()

        if key is not None:
            with entry.idempotent_lock:
                cached = entry.idempotent.get(key)
                if cached is not None:
                    lease.release()
                    return cached
                try:
                    future = self.scheduler.submit(
                        entry, lambda: self._run_turn(entry, request)
                    )
                except BaseException:
                    lease.release()
                    raise
                entry.idempotent[key] = future
                future.add_done_callback(release)
                return self._track_turn(request, future)

        try:
            future = self.scheduler.submit(entry, lambda: self._run_turn(entry, request))
        except BaseException:
            lease.release()
            raise
        future.add_done_callback(release)
        return self._track_turn(request, future)

    @staticmethod
    def _run_turn(
        entry: _SessionEntry, request: HostTurnRequest
    ) -> AgentConversationResult:
        """Run one turn while making the optional session lifecycle authoritative."""

        session = entry.session
        context = (
            session.begin_turn(
                turn_id=request.turn_id,
                attempt_id=request.attempt_id,
            )
            if session is not None
            else None
        )
        # Let AIAgent's existing conversation-loop boundary adopt the
        # host-owned turn. This avoids opening a second lifecycle for the
        # same request while keeping compatible facades unchanged.
        previous_context = getattr(entry.agent, "_agent_session_context", None)
        previous_session = getattr(entry.agent, "_agent_session", None)
        if session is not None and context is not None:
            try:
                setattr(entry.agent, "_agent_session_context", context)
                setattr(entry.agent, "_agent_session", session)
            except (AttributeError, TypeError):
                # Structural AgentProtocol implementations may use slots; the
                # host lifecycle remains authoritative even without adoption.
                pass
        try:
            result = entry.agent.run_conversation(
                request.user_message,
                **dict(request.conversation_kwargs),
            )
        except BaseException:
            if session is not None and context is not None:
                session.fail_turn(context)
            raise
        finally:
            if session is not None and context is not None:
                try:
                    if previous_context is None:
                        delattr(entry.agent, "_agent_session_context")
                    else:
                        setattr(entry.agent, "_agent_session_context", previous_context)
                    if previous_session is None:
                        delattr(entry.agent, "_agent_session")
                    else:
                        setattr(entry.agent, "_agent_session", previous_session)
                except (AttributeError, TypeError):
                    pass
        if session is not None and context is not None:
            if isinstance(result, dict) and (
                result.get("failed") or result.get("interrupted")
            ):
                session.fail_turn(context)
            else:
                session.complete_turn(context)
        return result

    @overload
    def run_turn(self, profile: HostTurnRequest) -> AgentConversationResult: ...

    @overload
    def run_turn(
        self,
        profile: str,
        session_id: str,
        user_message: str,
        **kwargs: Any,
    ) -> AgentConversationResult: ...

    def run_turn(
        self,
        profile: str | HostTurnRequest,
        session_id: str | None = None,
        user_message: str | None = None,
        **kwargs: Any,
    ) -> AgentConversationResult:
        """Synchronous adapter for legacy CLI/TUI call sites."""
        return self.submit(profile, session_id, user_message, **kwargs).result()

    def recover(
        self,
        profile: str,
        session_id: str,
        *,
        incarnation: str = "default",
        revision: int = 0,
    ) -> bool:
        identity = self.directory.resolve(
            profile, session_id, incarnation=incarnation, revision=revision
        )
        return self.pool.recover(identity)

    def status(self) -> HostStatusSnapshot:
        with self._lock:
            stopping = self._stopping
        return {
            "ready": not stopping,
            "stopping": stopping,
            "sessions": self.pool.snapshot(),
        }

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._stopping = True
        self.scheduler.shutdown(wait=wait)


__all__ = [
    "AgentHost",
    "HostBackpressure",
    "HostShutdown",
    "SessionDirectory",
    "SessionIdentity",
    "SessionPool",
    "TurnScheduler",
]
