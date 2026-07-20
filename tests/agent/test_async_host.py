from __future__ import annotations

import asyncio

import pytest

from agent.async_host import AsyncAgentHost


class AsyncAgent:
    def __init__(self):
        self.messages = []

    async def run_conversation_async(self, message, **kwargs):
        self.messages.append(message)
        await asyncio.sleep(0.001)
        return {"final_response": message, "completed": True}


@pytest.mark.asyncio
async def test_async_host_preserves_idempotency_and_session_order():
    created = []

    def factory(_identity):
        agent = AsyncAgent()
        created.append(agent)
        return agent

    async with AsyncAgentHost(factory, max_workers=2, max_pending=8) as host:
        one = await host.submit("profile", "session", "first", idempotency_key="same", turn_id="one")
        duplicate = await host.submit("profile", "session", "different", idempotency_key="same", turn_id="duplicate")
        assert one is duplicate
        assert await one == {"final_response": "first", "completed": True}
        assert host.status()["runtime"]["metrics"]["completed"] == 1

    assert len(created) == 1
    assert created[0].messages == ["first"]


@pytest.mark.asyncio
async def test_async_host_runs_legacy_sync_agent_off_event_loop():
    event_loop_thread = None

    class SyncAgent:
        def run_conversation(self, message, **kwargs):
            import threading

            nonlocal event_loop_thread
            event_loop_thread = threading.current_thread().name
            return {"final_response": message}

    async with AsyncAgentHost(lambda _identity: SyncAgent(), max_workers=1) as host:
        result = await host.run_turn("p", "s", "hello")

    assert result["final_response"] == "hello"
    assert event_loop_thread is not None
    assert "agent-runtime" not in event_loop_thread
