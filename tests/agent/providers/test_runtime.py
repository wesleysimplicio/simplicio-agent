"""Tests for the per-route ProviderRuntime (issue #224).

Uses in-memory fakes for the provider client/callable so nothing touches the
network or any credential. Covers: lifecycle reuse, retry + accounting,
credential isolation, atomic fallback, and clean shutdown (no orphan tasks).

Written as plain sync tests driving asyncio.run(...) so they run under the
repo's default pytest config without requiring the asyncio plugin.
"""
from __future__ import annotations

import asyncio

import pytest

from agent.providers.runtime import (
    ProviderRuntime,
    ProviderRuntimeRegistry,
    ProviderIsolationKey,
    StreamEvent,
    UsageAccounting,
)


class _FakeClient:
    def __init__(self, name: str, *, async_close: bool = False) -> None:
        self.name = name
        self.closed = False
        self._async_close = async_close

    async def aclose(self) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True


def _runtime_for(route_key, credential_slot, profile="openai", transport="chat",
                 callable_=None):
    client = _FakeClient(profile)
    if callable_ is None:
        async def call(prompt: str) -> str:
            return f"resp:{profile}:{prompt}"
    else:
        call = callable_
    return ProviderRuntime(profile, route_key, credential_slot, transport,
                           client, call)


def test_runtime_reuses_client_across_builds() -> None:
    async def _run():
        reg = ProviderRuntimeRegistry()
        calls = []

        def make_call(name: str):
            async def _call(prompt: str) -> str:
                calls.append(prompt)
                return f"resp:{name}:{prompt}"
            return _call

        rt1 = reg.get_or_build("openai", "route-a", "tenant-1", "chat",
                               _FakeClient("c1"), make_call("c1"))
        rt2 = reg.get_or_build("openai", "route-a", "tenant-1", "chat",
                               _FakeClient("c2"), make_call("c2"))
        # Same key -> reused, not rebuilt (connection lifecycle preserved).
        assert rt1 is rt2
        res = await rt1.run("hi")
        assert res.response == "resp:c1:hi"
        assert rt1.telemetry().built is True
        assert rt1.telemetry().live is True
    asyncio.run(_run())


def test_runtime_retries_then_accounts() -> None:
    async def _run():
        attempts = {"n": 0}

        async def flaky(prompt: str) -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("rate limit")  # transient
            return "ok"

        rt = _runtime_for("r", "t", callable_=flaky)
        res = await rt.run("p", retries=3)
        assert res.response == "ok"
        assert res.retries >= 2
        assert rt.telemetry().accounting.requests == 1
        assert rt.telemetry().accounting.retries >= 2
    asyncio.run(_run())


def test_runtime_fatal_error_raises_and_counts_error() -> None:
    async def _run():
        async def boom(prompt: str) -> str:
            raise RuntimeError("auth failed")  # non-transient

        rt = _runtime_for("r", "t", callable_=boom)
        with pytest.raises(RuntimeError):
            await rt.run("p", retries=2)
        assert rt.telemetry().accounting.errors == 1
        assert rt.telemetry().accounting.requests == 1
    asyncio.run(_run())


def test_credential_isolation_blocks_cross_tenant_swap() -> None:
    async def _run():
        rt = _runtime_for("r", "tenant-A")
        other = _runtime_for("r", "tenant-B", profile="anthropic",
                             transport="msg")
        with pytest.raises(ValueError):
            rt.swap_to(other)
    asyncio.run(_run())


def test_atomic_fallback_swaps_whole_capsule() -> None:
    async def _run():
        rt = _runtime_for("r", "tenant-1")
        other = _runtime_for("r", "tenant-1", profile="openai-backup")
        rt.swap_to(other)
        assert rt.profile_name == "openai-backup"
        assert rt.credential_slot == "tenant-1"
    asyncio.run(_run())


def test_shutdown_closes_client_and_marks_closed() -> None:
    async def _run():
        client = _FakeClient("c", async_close=True)
        rt = ProviderRuntime("openai", "r", "t", "chat", client,
                             (lambda p: asyncio.sleep(0, "x")))  # type: ignore
        assert rt.live is True
        await rt.run("p")  # exercise the runtime first
        return rt, client

    rt, client = asyncio.run(_run())
    rt.shutdown()
    assert rt.live is False
    assert client.closed is True
    rt.shutdown()  # idempotent
    with pytest.raises(RuntimeError):
        asyncio.run(rt.run("p"))


def test_registry_shutdown_all() -> None:
    async def _run():
        reg = ProviderRuntimeRegistry()
        c1 = _FakeClient("c1")
        c2 = _FakeClient("c2")
        reg.get_or_build("openai", "r1", "t1", "chat", c1,
                         (lambda p: asyncio.sleep(0, "x")))  # type: ignore
        reg.get_or_build("anthropic", "r2", "t2", "msg", c2,
                         (lambda p: asyncio.sleep(0, "y")))  # type: ignore
        await reg.get("r1", "t1").run("p")  # type: ignore[union-attr]
        await reg.get("r2", "t2").run("p")  # type: ignore[union-attr]
        return reg, c1, c2

    reg, c1, c2 = asyncio.run(_run())
    reg.shutdown_all()
    assert c1.closed and c2.closed
    assert reg.get("r1", "t1") is None


def test_usage_accounting_add() -> None:
    a = UsageAccounting()
    a.add(prompt_tokens=10, completion_tokens=5, total_tokens=15, retries=2,
          wall_s=0.3)
    assert a.requests == 1 and a.total_tokens == 15 and a.retries == 2
    a.add(error=True)
    assert a.errors == 1 and a.requests == 2


def test_registry_isolates_model_and_endpoint() -> None:
    reg = ProviderRuntimeRegistry()
    rt_a = reg.get_or_build(
        "openai", "route", "tenant", "chat", _FakeClient("a"),
        lambda prompt: asyncio.sleep(0, "a"),
        model="model-a", base_url="https://one.example",
    )
    rt_b = reg.get_or_build(
        "openai", "route", "tenant", "chat", _FakeClient("b"),
        lambda prompt: asyncio.sleep(0, "b"),
        model="model-b", base_url="https://two.example",
    )
    assert rt_a is not rt_b
    assert reg.get("route", "tenant") is None
    assert reg.get("route", "tenant", profile_name="openai", model="model-a", base_url="https://one.example") is rt_a
    assert rt_a.isolation_key == ProviderIsolationKey(
        provider="route", profile="openai", model="model-a",
        base_url="https://one.example", credential_slot="tenant",
    )
    reg.shutdown_all()


def test_stream_normalizes_chunks_closes_and_accounts_usage() -> None:
    async def _run() -> None:
        closed = {"value": False}

        async def source():
            try:
                yield {"type": "delta", "text": "hello", "usage": {"prompt_tokens": 4}}
                yield " world"
            finally:
                closed["value"] = True

        async def open_stream(prompt: str):
            assert prompt == "p"
            return source()

        rt = ProviderRuntime(
            "openai", "route", "tenant", "chat", _FakeClient("stream"),
            lambda prompt: asyncio.sleep(0, "unused"),
            supports_streaming=True,
            stream_call=open_stream,
        )
        events = [event async for event in rt.stream("p")]
        assert events == [
            StreamEvent(event_type="delta", data="hello", usage={"prompt_tokens": 4}),
            StreamEvent(data=" world"),
        ]
        assert closed["value"] is True
        accounting = rt.telemetry().accounting
        assert accounting.requests == 1
        assert accounting.prompt_tokens == 4

    asyncio.run(_run())


def test_stream_cancellation_closes_underlying_iterator() -> None:
    async def _run() -> None:
        started = asyncio.Event()
        closed = {"value": False}

        async def source():
            try:
                started.set()
                await asyncio.Event().wait()
                yield "never"
            finally:
                closed["value"] = True

        async def open_stream(prompt: str):
            return source()

        rt = ProviderRuntime(
            "openai", "route", "tenant", "chat", _FakeClient("stream"),
            lambda prompt: asyncio.sleep(0, "unused"),
            supports_streaming=True,
            stream_call=open_stream,
        )

        async def consume() -> None:
            async for _event in rt.stream("p"):
                pass

        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed["value"] is True

    asyncio.run(_run())


def test_run_extracts_provider_usage_without_retaining_response_text() -> None:
    async def _run() -> None:
        async def call(prompt: str):
            return {
                "text": "secret response should not enter telemetry",
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 7,
                    "total_tokens": 12,
                    "reasoning_tokens": 2,
                    "cache_read_input_tokens": 3,
                },
            }

        rt = ProviderRuntime("openai", "route", "tenant", "chat", _FakeClient("c"), call)
        result = await rt.run("secret prompt", retries=0)
        accounting = rt.telemetry().accounting
        assert result.response["text"].startswith("secret")
        assert accounting.prompt_tokens == 5
        assert accounting.completion_tokens == 7
        assert accounting.total_tokens == 12
        assert accounting.reasoning_tokens == 2
        assert accounting.cache_read_tokens == 3
        assert not hasattr(accounting, "text")

    asyncio.run(_run())