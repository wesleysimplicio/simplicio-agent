from __future__ import annotations

import pytest

from agent.async_host import AsyncAgentHost


class RecordingAgent:
    def __init__(self, created: list["RecordingAgent"]) -> None:
        self.messages: list[str] = []
        created.append(self)

    async def run_conversation_async(self, message: str, **_kwargs: object) -> dict[str, object]:
        self.messages.append(message)
        return {"final_response": message, "completed": True}


@pytest.mark.asyncio
async def test_deterministic_route_bypasses_agent_construction() -> None:
    created: list[RecordingAgent] = []

    async with AsyncAgentHost(lambda _identity: RecordingAgent(created)) as host:
        result = await host.run_turn("profile", "session", "ping")

    assert result["final_response"] == "pong"
    assert result["route_receipt"] == {
        "schema": "simplicio.agent-route/v1",
        "route": "deterministic",
        "reason": "deterministic intent: ping",
        "confidence": 1.0,
        "expected_tokens": 0,
        "actual_tokens": 0,
        "cache_hit": None,
        "model": None,
        "backend": None,
        "escalation": None,
        "verification": "PASS",
    }
    assert created == []


@pytest.mark.asyncio
async def test_reasoning_miss_uses_shared_runtime_and_receipt() -> None:
    created: list[RecordingAgent] = []

    async with AsyncAgentHost(lambda _identity: RecordingAgent(created), max_workers=1) as host:
        result = await host.run_turn("profile", "session", "explain this change")

    assert result["final_response"] == "explain this change"
    assert result["route_receipt"]["route"] == "frontier_reasoning"
    assert result["route_receipt"]["verification"] == "PASS"
    assert len(created) == 1


@pytest.mark.asyncio
async def test_deterministic_effect_is_blocked_without_runtime_gate() -> None:
    created: list[RecordingAgent] = []

    async with AsyncAgentHost(lambda _identity: RecordingAgent(created)) as host:
        result = await host.run_turn("profile", "session", "list files")

    assert result["failed"] is True
    assert result["route_receipt"]["route"] == "blocked"
    assert result["route_receipt"]["verification"] == "UNVERIFIED"
    assert created == []


@pytest.mark.asyncio
async def test_deterministic_effect_runs_only_through_supplied_runtime_gate() -> None:
    created: list[RecordingAgent] = []
    calls: list[dict[str, object]] = []

    def runtime_gate(tool_call: dict[str, object]) -> dict[str, object]:
        calls.append(tool_call)
        return {"final_response": "runtime result", "completed": True}

    async with AsyncAgentHost(
        lambda _identity: RecordingAgent(created), deterministic_effect=runtime_gate
    ) as host:
        result = await host.run_turn("profile", "session", "list files")

    assert result["final_response"] == "runtime result"
    assert calls == [{"tool": "list_files", "args": {"path": "."}}]
    assert result["route_receipt"]["route"] == "deterministic"
    assert result["route_receipt"]["verification"] == "PASS"
    assert created == []
