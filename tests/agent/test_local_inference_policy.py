from __future__ import annotations

import asyncio

import pytest

from agent.local_inference_policy import (
    LOCAL_INFERENCE_PAUSED,
    LocalInferencePausedError,
    ensure_local_inference_allowed,
    local_inference_receipt,
)
from agent.providers.router import AsyncProviderRouter, ProviderRoute, ProviderRouter


def test_local_route_is_paused_without_runner_or_fallback(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    calls: list[str] = []
    router = ProviderRouter(routes=(
        ProviderRoute("ollama", "local", lambda _: calls.append("local") or "local"),
        ProviderRoute("remote", "remote", lambda _: calls.append("remote") or "remote"),
    ))

    assert router.call("safe").provider == "remote"
    assert calls == ["remote"]
    assert router.health()[0] == {
        "name": "ollama", "kind": "local", "available": False,
        "reason": LOCAL_INFERENCE_PAUSED,
    }


def test_paused_local_route_has_stable_reason_and_receipt(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    with pytest.raises(LocalInferencePausedError, match=LOCAL_INFERENCE_PAUSED) as exc:
        ensure_local_inference_allowed(provider="ollama", base_url="http://127.0.0.1:11434", model="qwen")

    assert exc.value.reason == LOCAL_INFERENCE_PAUSED
    assert exc.value.receipt["reason"] == LOCAL_INFERENCE_PAUSED
    assert exc.value.receipt["enabled"] is False


def test_only_exact_opt_in_reenables_a_local_route(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", "true")
    with pytest.raises(LocalInferencePausedError):
        ensure_local_inference_allowed(provider="ollama")

    monkeypatch.setenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", "enabled")
    ensure_local_inference_allowed(provider="ollama")
    assert local_inference_receipt(provider="ollama")["enabled"] is True


def test_async_router_does_not_invoke_paused_local_route(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_AGENT_LOCAL_INFERENCE", raising=False)
    calls: list[str] = []

    async def local(_: str) -> str:
        calls.append("local")
        return "local"

    async def remote(_: str) -> str:
        calls.append("remote")
        return "remote"

    result = asyncio.run(AsyncProviderRouter(routes=(
        ("local", "local", local, lambda: True),
        ("remote", "remote", remote, lambda: True),
    )).call("safe"))

    assert result.provider == "remote"
    assert calls == ["remote"]
