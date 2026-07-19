"""Structured async runtime for bounded agent work.

The context is the single async concurrency boundary for new integrations. It
uses stdlib ``asyncio`` so the core remains dependency-light; an entrypoint may
install uvloop before creating this context. Library code never changes the
process-wide event-loop policy.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

RUNTIME_CONTEXT_SCHEMA = "simplicio-agent/runtime-context/v1"
LOOP_HUB_ADAPTER_SCHEMA = "simplicio-agent/loop-hub-adapter/v1"


class RuntimeBackpressure(RuntimeError):
    """Raised when the bounded runtime queue cannot admit more work."""


class RuntimeClosed(RuntimeError):
    """Raised when work is submitted after shutdown started."""


class LoopHubProtocol(Protocol):
    async def submit(self, task_id: str, payload: dict[str, Any]) -> Any: ...

    async def progress(self, task_id: str, payload: dict[str, Any]) -> Any: ...

    async def cancel(self, task_id: str) -> Any: ...

    async def result(self, task_id: str, payload: dict[str, Any]) -> Any: ...


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class StandaloneLoopHub:
    """Local Loop Hub fallback with the same versioned shape as remote mode."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}

    async def submit(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._records[task_id] = {"state": "queued", "payload": dict(payload)}
        return {"schema": LOOP_HUB_ADAPTER_SCHEMA, "mode": "standalone", "task_id": task_id}

    async def progress(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._records.setdefault(task_id, {})
        record.update({"state": "running", "progress": dict(payload)})
        return {"schema": LOOP_HUB_ADAPTER_SCHEMA, "mode": "standalone", "task_id": task_id}

    async def cancel(self, task_id: str) -> dict[str, Any]:
        record = self._records.setdefault(task_id, {})
        record["state"] = "cancelled"
        return {"schema": LOOP_HUB_ADAPTER_SCHEMA, "mode": "standalone", "task_id": task_id}

    async def result(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._records.setdefault(task_id, {})
        record.update({"state": "done", "result": dict(payload)})
        return {"schema": LOOP_HUB_ADAPTER_SCHEMA, "mode": "standalone", "task_id": task_id}


class LoopHubAdapter:
    """Opt-in bridge to a Loop Hub; standalone mode is deterministic fallback."""

    def __init__(self, backend: LoopHubProtocol | None = None) -> None:
        self.backend = backend or StandaloneLoopHub()
        self.mode = "hub" if backend is not None else "standalone"

    async def submit(self, task_id: str, payload: dict[str, Any]) -> Any:
        return await _maybe_await(self.backend.submit(task_id, payload))

    async def progress(self, task_id: str, payload: dict[str, Any]) -> Any:
        return await _maybe_await(self.backend.progress(task_id, payload))

    async def cancel(self, task_id: str) -> Any:
        return await _maybe_await(self.backend.cancel(task_id))

    async def result(self, task_id: str, payload: dict[str, Any]) -> Any:
        return await _maybe_await(self.backend.result(task_id, payload))


@dataclass
class RuntimeMetrics:
    submitted: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    rejected: int = 0
    active: int = 0
    queued: int = 0
    max_active: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def snapshot(self) -> dict[str, Any]:
        elapsed_s = max(0.0, time.monotonic() - self.started_at)
        return {
            "schema": "simplicio-agent/runtime-metrics/v1",
            "submitted": self.submitted,
            "completed": self.completed,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "rejected": self.rejected,
            "active": self.active,
            "queued": self.queued,
            "max_active": self.max_active,
            "elapsed_s": round(elapsed_s, 6),
            "throughput_per_s": round(self.completed / elapsed_s, 2) if elapsed_s else 0.0,
        }


@dataclass
class _WorkItem:
    task_id: str
    factory: Callable[[], Awaitable[Any] | Any]
    key: str | None
    payload: dict[str, Any]
    future: asyncio.Future[Any]
    task: asyncio.Task[Any] | None = None
    cancelled: bool = False


class AgentRuntimeContext:
    """Bounded, structured-concurrency executor for agent tasks."""

    def __init__(
        self,
        *,
        max_workers: int = 4,
        max_pending: int = 64,
        max_session_locks: int = 256,
        loop_hub: LoopHubAdapter | None = None,
    ) -> None:
        if max_workers < 1 or max_pending < 1 or max_session_locks < 1:
            raise ValueError("runtime limits must be positive")
        self.max_workers = max_workers
        self.max_pending = max_pending
        self.max_session_locks = max_session_locks
        self.loop_hub = loop_hub or LoopHubAdapter()
        self.metrics = RuntimeMetrics()
        self._queue: asyncio.Queue[_WorkItem | None] = asyncio.Queue(maxsize=max_pending)
        self._group: asyncio.TaskGroup | None = None
        self._workers: list[asyncio.Task[Any]] = []
        self._inflight: dict[str, _WorkItem] = {}
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._accepting = False

    @property
    def started(self) -> bool:
        return self._group is not None and self._accepting

    async def __aenter__(self) -> "AgentRuntimeContext":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.shutdown(wait=exc_type is None)

    async def start(self) -> None:
        if self.started:
            return
        if self._group is not None:
            raise RuntimeError("runtime context cannot be restarted")
        self._group = asyncio.TaskGroup()
        await self._group.__aenter__()
        self._accepting = True
        self._workers = [self._group.create_task(self._worker()) for _ in range(self.max_workers)]

    async def submit(
        self,
        factory: Callable[[], Awaitable[Any] | Any],
        *,
        task_id: str | None = None,
        key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> asyncio.Future[Any]:
        if not self.started:
            raise RuntimeClosed("runtime context is not running")
        identifier = task_id or uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        item = _WorkItem(identifier, factory, key, dict(payload or {}), future)
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull as exc:
            self.metrics.rejected += 1
            raise RuntimeBackpressure("runtime task queue is full; retry later") from exc
        self._inflight[identifier] = item
        self.metrics.submitted += 1
        self.metrics.queued += 1
        await self.loop_hub.submit(identifier, item.payload)
        return future

    async def run(
        self,
        factory: Callable[[], Awaitable[Any] | Any],
        *,
        task_id: str | None = None,
        key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        identifier = task_id or uuid.uuid4().hex
        future = await self.submit(factory, task_id=identifier, key=key, payload=payload)
        try:
            return await future
        except asyncio.CancelledError:
            await self.cancel(identifier)
            raise

    async def cancel(self, task_id: str) -> bool:
        item = self._inflight.get(task_id)
        if item is None:
            return False
        item.cancelled = True
        if item.task is None:
            if not item.future.done():
                item.future.cancel()
            await self.loop_hub.cancel(task_id)
            return True
        item.task.cancel()
        await self.loop_hub.cancel(task_id)
        return True

    async def shutdown(self, *, wait: bool = True) -> None:
        if self._group is None:
            return
        self._accepting = False
        if wait:
            await self._queue.join()
        else:
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                item.cancelled = True
                if not item.future.done():
                    item.future.cancel()
                self.metrics.cancelled += 1
                self.metrics.queued = max(0, self.metrics.queued - 1)
                self._queue.task_done()
                await self.loop_hub.cancel(item.task_id)
            for item in tuple(self._inflight.values()):
                if item.task is not None:
                    item.task.cancel()
            await self._queue.join()

        for _ in self._workers:
            await self._queue.put(None)
        group, self._group = self._group, None
        self._workers = []
        await group.__aexit__(None, None, None)

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_CONTEXT_SCHEMA,
            "state": "running" if self.started else "stopped",
            "max_workers": self.max_workers,
            "max_pending": self.max_pending,
            "hub_mode": self.loop_hub.mode,
            "metrics": self.metrics.snapshot(),
        }

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        self._locks.move_to_end(key)
        while len(self._locks) > self.max_session_locks:
            oldest, candidate = next(iter(self._locks.items()))
            if candidate.locked():
                self._locks.move_to_end(oldest)
                break
            self._locks.pop(oldest)
        return lock

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            self._inflight[item.task_id] = item
            self.metrics.queued = max(0, self.metrics.queued - 1)
            self.metrics.active += 1
            self.metrics.max_active = max(self.metrics.max_active, self.metrics.active)
            try:
                if item.cancelled:
                    if not item.future.done():
                        item.future.cancel()
                    self.metrics.cancelled += 1
                    continue
                await self.loop_hub.progress(item.task_id, {"state": "running"})
                execution = asyncio.create_task(self._execute_item(item))
                item.task = execution
                value = await execution
                if not item.future.done():
                    item.future.set_result(value)
                self.metrics.completed += 1
                await self.loop_hub.result(item.task_id, {"state": "done"})
            except asyncio.CancelledError:
                self.metrics.cancelled += 1
                if not item.future.done():
                    item.future.cancel()
                if not item.cancelled:
                    await self.loop_hub.cancel(item.task_id)
            except BaseException as exc:  # noqa: BLE001
                self.metrics.failed += 1
                if not item.future.done():
                    item.future.set_exception(exc)
                await self.loop_hub.result(item.task_id, {"state": "failed", "error": str(exc)})
            finally:
                self.metrics.active = max(0, self.metrics.active - 1)
                self._inflight.pop(item.task_id, None)
                self._queue.task_done()

    async def _execute_item(self, item: _WorkItem) -> Any:
        if item.key is None:
            return await _maybe_await(item.factory())
        async with self._lock_for(item.key):
            return await _maybe_await(item.factory())


__all__ = [
    "AgentRuntimeContext",
    "LOOP_HUB_ADAPTER_SCHEMA",
    "LoopHubAdapter",
    "LoopHubProtocol",
    "RuntimeBackpressure",
    "RuntimeClosed",
    "RuntimeMetrics",
    "StandaloneLoopHub",
]
