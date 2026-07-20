from __future__ import annotations

import asyncio

import pytest

from agent.runtime_context import (
    AgentRuntimeContext,
    LoopHubAdapter,
    RuntimeBackpressure,
    RuntimeClosed,
)


@pytest.mark.asyncio
async def test_runtime_bounds_parallelism_and_reports_metrics():
    active = 0
    peak = 0
    guard = asyncio.Lock()

    async def work(index: int):
        nonlocal active, peak
        async with guard:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.005)
        async with guard:
            active -= 1
        return index

    async with AgentRuntimeContext(max_workers=3, max_pending=32) as runtime:
        values = await asyncio.gather(
            *(runtime.run(lambda i=i: work(i), task_id=f"task-{i}") for i in range(20))
        )
        metrics = runtime.snapshot()["metrics"]

    assert values == list(range(20))
    assert peak <= 3
    assert metrics["max_active"] <= 3
    assert metrics["completed"] == 20
    assert metrics["failed"] == 0


@pytest.mark.asyncio
async def test_runtime_rejects_work_when_queue_is_full():
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked():
        started.set()
        await release.wait()
        return "done"

    runtime = AgentRuntimeContext(max_workers=1, max_pending=1)
    await runtime.start()
    try:
        first = await runtime.submit(blocked, task_id="first")
        await started.wait()
        second = await runtime.submit(lambda: "queued", task_id="second")
        with pytest.raises(RuntimeBackpressure):
            await runtime.submit(lambda: "rejected", task_id="third")
        release.set()
        assert await first == "done"
        assert await second == "queued"
        assert runtime.metrics.rejected == 1
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_same_key_is_serialized_but_different_keys_can_overlap():
    events: list[tuple[str, str]] = []
    gate = asyncio.Event()

    async def work(label: str):
        events.append((label, "start"))
        if label == "a1":
            await gate.wait()
        events.append((label, "end"))
        return label

    async with AgentRuntimeContext(max_workers=3, max_pending=8) as runtime:
        first = asyncio.create_task(runtime.run(lambda: work("a1"), key="session-a", task_id="a1"))
        await asyncio.sleep(0)
        second = asyncio.create_task(runtime.run(lambda: work("a2"), key="session-a", task_id="a2"))
        third = asyncio.create_task(runtime.run(lambda: work("b1"), key="session-b", task_id="b1"))
        await asyncio.sleep(0.01)
        assert ("a2", "start") not in events
        assert ("b1", "start") in events
        gate.set()
        assert await first == "a1"
        assert await second == "a2"
        assert await third == "b1"

    assert events.index(("a1", "end")) < events.index(("a2", "start"))


@pytest.mark.asyncio
async def test_cancel_propagates_to_hub_and_does_not_leave_active_work():
    class Hub:
        def __init__(self):
            self.events = []

        async def submit(self, task_id, payload):
            self.events.append(("submit", task_id))

        async def progress(self, task_id, payload):
            self.events.append(("progress", task_id))

        async def cancel(self, task_id):
            self.events.append(("cancel", task_id))

        async def result(self, task_id, payload):
            self.events.append(("result", task_id))

    gate = asyncio.Event()
    hub = Hub()
    runtime = AgentRuntimeContext(loop_hub=LoopHubAdapter(hub))
    await runtime.start()
    try:
        future = await runtime.submit(lambda: gate.wait(), task_id="cancel-me")
        await asyncio.sleep(0.01)
        assert await runtime.cancel("cancel-me") is True
        with pytest.raises(asyncio.CancelledError):
            await future
        assert ("cancel", "cancel-me") in hub.events
        assert runtime.metrics.active == 0
        assert runtime.metrics.cancelled >= 1
    finally:
        await runtime.shutdown(wait=False)


@pytest.mark.asyncio
async def test_runtime_is_standalone_without_hub_and_rejects_after_shutdown():
    runtime = AgentRuntimeContext(max_workers=1)
    async with runtime:
        assert runtime.snapshot()["hub_mode"] == "standalone"
        assert await runtime.run(lambda: 42) == 42
    with pytest.raises(RuntimeClosed):
        await runtime.submit(lambda: 1)
