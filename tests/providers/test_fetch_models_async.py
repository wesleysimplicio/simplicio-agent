"""Async provider catalog tests for issue #494."""

import asyncio
import json

import pytest

from providers.base import ProviderProfile


async def _serve_json(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_fetch_models_async_uses_native_http_and_preserves_headers():
    received = {}

    async def handler(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        received["request"] = request.decode("latin-1")
        body = json.dumps({"data": [{"id": "async-model"}]}).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n"
              "Connection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server, port = await _serve_json(handler)
    try:
        profile = ProviderProfile(
            name="test",
            base_url=f"http://127.0.0.1:{port}",
            default_headers={"x-provider-header": "header-value"},
        )
        result = await profile.fetch_models_async(api_key="test-key", timeout=1.0)
    finally:
        server.close()
        await server.wait_closed()

    assert result == ["async-model"]
    assert "Authorization: Bearer test-key" in received["request"]
    assert "x-provider-header: header-value" in received["request"]


@pytest.mark.asyncio
async def test_fetch_models_async_propagates_cancellation_and_closes_request(monkeypatch):
    started = asyncio.Event()
    closed = False

    class BlockingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            nonlocal closed
            closed = True

        async def get(self, *_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: BlockingClient())
    task = asyncio.create_task(
        ProviderProfile(name="test", base_url="http://provider.test").fetch_models_async(
            timeout=30.0
        )
    )
    try:
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        assert closed is True


@pytest.mark.asyncio
async def test_fetch_models_async_without_endpoint_fails_closed():
    assert await ProviderProfile(name="test").fetch_models_async() is None
