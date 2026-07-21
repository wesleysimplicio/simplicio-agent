from __future__ import annotations

import asyncio

import pytest

from agent.providers.router import AsyncProviderRouter, ProviderRoute, ProviderRouter


def test_router_skips_available_local_route_while_pause_is_active(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    calls: list[str] = []
    router = ProviderRouter(
        routes=(
            ProviderRoute("remote", "remote", lambda prompt: calls.append("remote") or "r"),
            ProviderRoute("local", "local", lambda prompt: calls.append("local") or "l"),
        )
    )

    result = router.call("hello")

    assert result.provider == "remote"
    assert calls == ["remote"]
    assert router.health() == (
        {"name": "remote", "kind": "remote", "available": True, "reason": None},
        {"name": "local", "kind": "local", "available": False, "reason": "LOCAL_INFERENCE_PAUSED"},
    )


def test_router_does_not_invoke_paused_local_route(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    router = ProviderRouter(
        routes=(
            ProviderRoute("local", "local", lambda prompt: (_ for _ in ()).throw(RuntimeError("offline"))),
            ProviderRoute("remote", "remote", lambda prompt: "remote-ok"),
        ),
        max_retries=0,
    )

    result = router.call("hello")

    assert result.provider == "remote"
    assert result.response == "remote-ok"


def test_router_fails_closed_without_available_routes():
    router = ProviderRouter(routes=(ProviderRoute("local", "local", lambda prompt: "never", lambda: False),))

    with pytest.raises(RuntimeError, match="no available"):
        router.call("hello")


def test_async_router_skips_paused_local_route(monkeypatch):
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

    assert asyncio.run(invoke()).provider == "remote"
