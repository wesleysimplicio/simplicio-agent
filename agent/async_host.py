"""Async facade over the existing session pool and AgentHost contracts."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Optional

from .host import HostBackpressure, HostShutdown, SessionDirectory, SessionIdentity, SessionPool
from .protocol import AgentConversationResult, AgentProtocol, AgentSessionProtocol, HostTurnRequest
from .runtime_context import AgentRuntimeContext, RuntimeBackpressure


class AsyncAgentHost:
    """Async-first host with bounded shared scheduling and session ordering."""

    def __init__(
        self,
        agent_factory: Callable[[SessionIdentity], AgentProtocol],
        *,
        max_sessions: int = 32,
        max_workers: int = 4,
        max_pending: int = 64,
        directory: Optional[SessionDirectory] = None,
        session_factory: Optional[Callable[[SessionIdentity], AgentSessionProtocol]] = None,
        runtime: AgentRuntimeContext | None = None,
    ) -> None:
        self.directory = directory or SessionDirectory()
        self.pool = SessionPool(agent_factory, max_sessions=max_sessions, session_factory=session_factory)
        self.runtime = runtime or AgentRuntimeContext(max_workers=max_workers, max_pending=max_pending)
        self._stopping = False

    async def __aenter__(self) -> "AsyncAgentHost":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.shutdown(wait=exc_type is None)

    async def start(self) -> None:
        if self._stopping:
            raise HostShutdown("agent host is draining")
        await self.runtime.start()

    async def submit(
        self,
        profile: str | HostTurnRequest,
        session_id: str | None = None,
        user_message: str | None = None,
        *,
        idempotency_key: str | None = None,
        turn_id: str | None = None,
        attempt_id: str = "0",
        incarnation: str = "default",
        revision: int = 0,
        **conversation_kwargs: Any,
    ) -> asyncio.Future[AgentConversationResult]:
        request = self._coerce_request(
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
        if self._stopping:
            raise HostShutdown("agent host is draining")
        if not self.runtime.started:
            await self.runtime.start()
        identity = self.directory.resolve(
            request.profile,
            request.session_id,
            incarnation=request.incarnation,
            revision=request.revision,
        )
        lease = self.pool.acquire(identity)
        entry = lease.entry
        key = request.idempotency_key
        if key is not None:
            cache = entry.async_idempotent
            cached = cache.get(key)
            if cached is not None:
                lease.release()
                return cached
        try:
            future = await self.runtime.submit(
                lambda: self._run_turn(entry, request),
                task_id=request.turn_id,
                key=f"{identity.profile}:{identity.session_id}:{identity.incarnation}:{identity.revision}",
                payload={"profile": identity.profile, "session_id": identity.session_id},
            )
        except (RuntimeBackpressure, RuntimeError):
            lease.release()
            raise
        if key is not None:
            entry.async_idempotent[key] = future
        future.add_done_callback(lambda _done: lease.release())
        return future

    async def run_turn(
        self,
        profile: str | HostTurnRequest,
        session_id: str | None = None,
        user_message: str | None = None,
        **kwargs: Any,
    ) -> AgentConversationResult:
        future = await self.submit(profile, session_id, user_message, **kwargs)
        return await future

    async def cancel(self, task_id: str) -> bool:
        return await self.runtime.cancel(task_id)

    def status(self) -> dict[str, Any]:
        return {
            "ready": not self._stopping,
            "stopping": self._stopping,
            "sessions": self.pool.snapshot(),
            "runtime": self.runtime.snapshot(),
        }

    async def shutdown(self, *, wait: bool = True) -> None:
        self._stopping = True
        await self.runtime.shutdown(wait=wait)
        for identity in tuple(self.pool._entries):
            try:
                self.pool.recover(identity)
            except HostBackpressure:
                pass

    @staticmethod
    def _coerce_request(
        profile: str | HostTurnRequest,
        session_id: str | None,
        user_message: str | None,
        **kwargs: Any,
    ) -> HostTurnRequest:
        if isinstance(profile, HostTurnRequest):
            return profile
        if session_id is None or user_message is None:
            raise TypeError("session_id and user_message are required")
        return HostTurnRequest(
            profile=profile,
            session_id=session_id,
            user_message=user_message,
            idempotency_key=kwargs.pop("idempotency_key", None),
            turn_id=kwargs.pop("turn_id", None),
            attempt_id=kwargs.pop("attempt_id", "0"),
            incarnation=kwargs.pop("incarnation", "default"),
            revision=kwargs.pop("revision", 0),
            conversation_kwargs=kwargs,
        )

    @staticmethod
    async def _run_turn(entry: Any, request: HostTurnRequest) -> AgentConversationResult:
        session = entry.session
        context = None
        if session is not None:
            context = session.begin_turn(turn_id=request.turn_id, attempt_id=request.attempt_id)
            if inspect.isawaitable(context):
                context = await context
        try:
            async_method = getattr(entry.agent, "run_conversation_async", None)
            if callable(async_method):
                result = async_method(request.user_message, **dict(request.conversation_kwargs))
                result = await result if inspect.isawaitable(result) else result
            else:
                result = await asyncio.to_thread(
                    entry.agent.run_conversation,
                    request.user_message,
                    **dict(request.conversation_kwargs),
                )
            if session is not None and context is not None:
                completed = session.complete_turn(context)
                if inspect.isawaitable(completed):
                    await completed
            return result
        except BaseException:
            if session is not None and context is not None:
                failed = session.fail_turn(context)
                if inspect.isawaitable(failed):
                    await failed
            raise


__all__ = ["AsyncAgentHost"]
