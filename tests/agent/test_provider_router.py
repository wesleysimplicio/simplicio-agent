from __future__ import annotations

import asyncio

import pytest

from agent.local_inference_policy import LOCAL_INFERENCE_PAUSED, LocalInferencePausedError
from agent.providers.router import AsyncProviderRouter, ProviderRoute, ProviderRouter


def test_router_rejects_paused_local_route_without_remote_fallback(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    calls: list[str] = []
    router = ProviderRouter(
        routes=(
            ProviderRoute("remote", "remote", lambda prompt: calls.append("remote") or "r"),
            ProviderRoute("local", "local", lambda prompt: calls.append("local") or "l"),
        )
    )

    with pytest.raises(LocalInferencePausedError, match=LOCAL_INFERENCE_PAUSED):
        router.call("hello")

    assert calls == []
    assert router.health() == (
        {"name": "remote", "kind": "remote", "available": True, "reason": None},
        {"name": "local", "kind": "local", "available": False, "reason": "LOCAL_INFERENCE_PAUSED"},
    )


def test_router_permits_remote_only_after_explicit_remote_selection(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    router = ProviderRouter(
        routes=(
            ProviderRoute("local", "local", lambda prompt: (_ for _ in ()).throw(RuntimeError("offline"))),
            ProviderRoute("remote", "remote", lambda prompt: "remote-ok"),
        ),
        prefer_local=False,
        max_retries=0,
    )

    result = router.call("hello")

    assert result.provider == "remote"
    assert result.response == "remote-ok"


def test_router_fails_closed_without_available_routes():
    router = ProviderRouter(
        routes=(ProviderRoute("local", "local", lambda prompt: "never", lambda: False),),
        prefer_local=False,
    )

    with pytest.raises(RuntimeError, match="no available"):
        router.call("hello")


def test_async_router_rejects_paused_local_route_without_remote_fallback(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    async def _async_value(value: str) -> str:
        return value

    async def invoke():
        return await AsyncProviderRouter(
            routes=(
                ("remote", "remote", lambda prompt: _async_value("remote"), lambda: True),
                ("local", "local", lambda prompt: _async_value("local"), lambda: True),
            )
        ).call("hello")

    with pytest.raises(LocalInferencePausedError, match=LOCAL_INFERENCE_PAUSED):
        asyncio.run(invoke())
