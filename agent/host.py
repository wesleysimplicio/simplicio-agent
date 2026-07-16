"""Embedded AgentHost: durable session identity, pooling, and turn scheduling.

The host is deliberately an adapter around ``AIAgent`` rather than a second
agent implementation.  A surface supplies an ``agent_factory`` and every turn
still runs through the existing ``AIAgent.run_conversation`` contract.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
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
        self._idempotent: dict[tuple[SessionIdentity, str], Future[Any]] = {}

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
        key = (identity, request.idempotency_key) if request.idempotency_key else None
        with self._lock:
            if self._stopping:
                raise HostShutdown("agent host is draining")
            if key is not None and key in self._idempotent:
                return self._idempotent[key]

        lease = self.pool.acquire(identity)
        try:
            future = self.scheduler.submit(
                lease.entry,
                lambda: self._run_turn(lease.entry, request),
            )
        except BaseException:
            lease.release()
            raise

        def release(done: Future[Any]) -> None:
            lease.release()

        future.add_done_callback(release)
        if key is not None:
            with self._lock:
                self._idempotent[key] = future
        return future

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
        try:
            result = entry.agent.run_conversation(
                request.user_message,
                **dict(request.conversation_kwargs),
            )
        except BaseException:
            if session is not None and context is not None:
                session.fail_turn(context)
            raise
        if session is not None and context is not None:
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
