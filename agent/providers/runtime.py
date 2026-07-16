"""ProviderRuntime: per-route, credential-isolated provider lifecycle (issue #224).

A ``ProviderRuntime`` binds together, for one route/credential isolation key:

* a provider profile and transport tag;
* the concrete client/SDK and its connection lifecycle;
* retry, deadline, streaming, usage accounting, and redacted telemetry.

Provider-specific SDKs remain responsible for their own protocol semantics.  This
module owns only the stable lifecycle boundary around them and is pure stdlib so
it can be tested with in-memory fakes.
"""
from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterable, AsyncIterator, Awaitable, Callable, Dict, Mapping, Optional, Sequence, Tuple, Union

from agent.providers.fallback_chain import (
    AsyncProviderChain,
    ProviderChainMetrics,
    ProviderResult,
)


@dataclass(frozen=True)
class ProviderIsolationKey:
    """All attributes that must match before a client can be reused."""

    provider: str
    profile: str
    model: str = ""
    base_url: str = ""
    proxy: str = ""
    tls_profile: str = ""
    credential_slot: str = ""

    def as_tuple(self) -> tuple[str, ...]:
        """Return a stable, secret-free representation for diagnostics."""

        return (
            self.provider,
            self.profile,
            self.model,
            self.base_url,
            self.proxy,
            self.tls_profile,
            self.credential_slot,
        )


@dataclass(frozen=True)
class StreamEvent:
    """Normalized, provider-neutral event emitted by :meth:`ProviderRuntime.stream`."""

    event_type: str = "delta"
    data: Any = None
    usage: Optional[Mapping[str, Any]] = None


@dataclass
class UsageAccounting:
    """Per-runtime usage / cost accounting (redacted: no prompt text)."""

    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    errors: int = 0
    retries: int = 0
    switches: int = 0
    wall_s: float = 0.0

    def add(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        reasoning_tokens: int = 0,
        cache_read_tokens: int = 0,
        retries: int = 0,
        switches: int = 0,
        wall_s: float = 0.0,
        error: bool = False,
    ) -> None:
        self.requests += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.reasoning_tokens += reasoning_tokens
        self.cache_read_tokens += cache_read_tokens
        self.retries += retries
        self.switches += switches
        self.wall_s += wall_s
        if error:
            self.errors += 1

    @staticmethod
    def _usage_payload(value: Any) -> Optional[Any]:
        if isinstance(value, StreamEvent):
            return value.usage
        if isinstance(value, ProviderResult):
            value = value.response
        if isinstance(value, Mapping):
            return value.get("usage")
        return getattr(value, "usage", None)

    @staticmethod
    def _usage_value(usage: Any, *names: str) -> int:
        for name in names:
            if isinstance(usage, Mapping):
                value = usage.get(name)
            else:
                value = getattr(usage, name, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
        return 0

    def record_usage(self, value: Any) -> None:
        """Accumulate provider-reported usage without retaining response content."""

        usage = self._usage_payload(value)
        if usage is None:
            return
        self.prompt_tokens += self._usage_value(
            usage, "prompt_tokens", "input_tokens"
        )
        self.completion_tokens += self._usage_value(
            usage, "completion_tokens", "output_tokens"
        )
        self.total_tokens += self._usage_value(usage, "total_tokens")
        self.reasoning_tokens += self._usage_value(
            usage, "reasoning_tokens", "output_reasoning_tokens"
        )
        self.cache_read_tokens += self._usage_value(
            usage,
            "cache_read_tokens",
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
            "cached_tokens",
        )


@dataclass
class RuntimeTelemetry:
    """Redacted telemetry snapshot — never embeds prompts or secrets."""

    profile: str
    route_key: str
    credential_slot: str
    built: bool
    live: bool
    accounting: UsageAccounting


StreamCall = Callable[
    [str], Union[Awaitable[AsyncIterable[Any]], AsyncIterable[Any]]
]


@dataclass
class _ProviderCapsule:
    profile_name: str
    transport_tag: str
    credential_slot: str
    client: Any
    call: Callable[..., Awaitable[Any]]
    supports_streaming: bool
    stream_call: Optional[StreamCall] = None


class ProviderRuntime:
    """One live, measurable provider route bound to a credential slot."""

    def __init__(
        self,
        profile_name: str,
        route_key: str,
        credential_slot: str,
        transport_tag: str,
        client: Any,
        call: Callable[..., Awaitable[Any]],
        *,
        supports_streaming: bool = False,
        stream_call: Optional[StreamCall] = None,
        deadline_budget_s: float = 30.0,
        isolation_key: Optional[ProviderIsolationKey] = None,
    ) -> None:
        self.profile_name = profile_name
        self.route_key = route_key
        self.credential_slot = credential_slot
        self.transport_tag = transport_tag
        self.isolation_key = isolation_key or ProviderIsolationKey(
            provider=route_key,
            profile=profile_name,
            credential_slot=credential_slot,
        )
        self._capsule = _ProviderCapsule(
            profile_name=profile_name,
            transport_tag=transport_tag,
            credential_slot=credential_slot,
            client=client,
            call=call,
            supports_streaming=supports_streaming and stream_call is not None,
            stream_call=stream_call,
        )
        self._deadline_budget_s = deadline_budget_s
        self._accounting = UsageAccounting()
        self._built_at = time.monotonic()
        self._live = True
        self._closed = False

    @property
    def live(self) -> bool:
        return self._live and not self._closed

    def built(self) -> bool:
        return self._capsule.client is not None

    def shutdown(self) -> None:
        """Close the SDK once and mark this runtime unavailable."""

        if self._closed:
            return
        client = self._capsule.client
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if callable(closer):
            try:
                if inspect.iscoroutinefunction(closer):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        asyncio.run(closer())  # type: ignore[arg-type]
                    else:
                        loop.create_task(closer())  # type: ignore[arg-type]
                else:
                    closer()
            except Exception:
                pass
        self._live = False
        self._closed = True

    def swap_to(self, other: "ProviderRuntime") -> None:
        """Atomically replace the complete provider capsule on fallback."""

        if other.credential_slot != self.credential_slot:
            raise ValueError(
                f"refusing to swap credential slot "
                f"{self.credential_slot!r} -> {other.credential_slot!r}"
            )
        self._capsule = other._capsule
        self.profile_name = other.profile_name
        self.transport_tag = other.transport_tag
        self.isolation_key = other.isolation_key

    @staticmethod
    def _event_from_chunk(chunk: Any) -> StreamEvent:
        if isinstance(chunk, StreamEvent):
            return chunk
        if isinstance(chunk, str):
            return StreamEvent(data=chunk)
        if isinstance(chunk, Mapping):
            event_type = str(chunk.get("type") or chunk.get("event") or "delta")
            data = chunk.get("data", chunk.get("delta", chunk.get("text", chunk)))
            usage = chunk.get("usage")
            return StreamEvent(event_type=event_type, data=data, usage=usage)
        event_type = str(getattr(chunk, "type", None) or "delta")
        data = getattr(chunk, "data", getattr(chunk, "delta", chunk))
        return StreamEvent(event_type=event_type, data=data, usage=getattr(chunk, "usage", None))

    async def stream(
        self,
        prompt: str,
        *,
        deadline_budget_s: Optional[float] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield normalized chunks and always close the underlying stream.

        A stream is deliberately not retried after it starts yielding: replaying
        partial output can duplicate text or tool calls. Cancellation is allowed
        to propagate after the iterator's close hook has run.
        """

        if self._closed:
            raise RuntimeError("ProviderRuntime is shut down")
        stream_call = self._capsule.stream_call
        if not self._capsule.supports_streaming or stream_call is None:
            raise RuntimeError("ProviderRuntime has no streaming callback")

        budget = self._deadline_budget_s if deadline_budget_s is None else deadline_budget_s
        started = time.monotonic()
        iterator: Optional[Any] = None
        try:
            candidate = stream_call(prompt)
            if inspect.isawaitable(candidate):
                remaining = max(0.0, budget - (time.monotonic() - started))
                iterator = await asyncio.wait_for(candidate, timeout=remaining)
            else:
                iterator = candidate
            if not hasattr(iterator, "__anext__"):
                raise TypeError("stream callback must return an async iterator")

            while True:
                remaining = budget - (time.monotonic() - started)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                event = self._event_from_chunk(chunk)
                self._accounting.record_usage(event)
                yield event
            self._accounting.add(wall_s=time.monotonic() - started)
        except asyncio.CancelledError:
            self._accounting.add(wall_s=time.monotonic() - started, error=True)
            raise
        except Exception:
            self._accounting.add(wall_s=time.monotonic() - started, error=True)
            raise
        finally:
            if iterator is not None:
                closer = getattr(iterator, "aclose", None) or getattr(iterator, "close", None)
                if callable(closer):
                    try:
                        result = closer()
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        pass

    async def run(
        self,
        prompt: str,
        *,
        idempotency_key: Optional[str] = None,
        retries: int = 3,
    ) -> ProviderResult:
        """Run one request under the global deadline and retry budget."""

        if self._closed:
            raise RuntimeError("ProviderRuntime is shut down")
        _ = idempotency_key or uuid.uuid4().hex
        start = time.monotonic()
        chain: AsyncProviderChain = AsyncProviderChain(
            providers=[(self.profile_name, self._capsule.call)],
            max_retries=retries,
        )
        try:
            result = await asyncio.wait_for(
                chain.call(prompt), timeout=self._deadline_budget_s
            )
        except Exception:
            self._accounting.add(error=True, retries=chain.metrics.retries)
            raise
        elapsed = time.monotonic() - start
        self._accounting.record_usage(result)
        self._accounting.add(
            retries=getattr(result, "retries", chain.metrics.retries),
            switches=chain.metrics.switches,
            wall_s=elapsed,
        )
        return result

    def telemetry(self) -> RuntimeTelemetry:
        return RuntimeTelemetry(
            profile=self.profile_name,
            route_key=self.route_key,
            credential_slot=self.credential_slot,
            built=self.built(),
            live=self.live,
            accounting=self._accounting,
        )


class ProviderRuntimeRegistry:
    """Owns one ``ProviderRuntime`` per complete isolation key."""

    def __init__(self) -> None:
        self._runtimes: Dict[ProviderIsolationKey, ProviderRuntime] = {}

    @staticmethod
    def _key(
        route_key: str,
        credential_slot: str,
        profile_name: str = "",
        model: str = "",
        base_url: str = "",
        proxy: str = "",
        tls_profile: str = "",
    ) -> ProviderIsolationKey:
        return ProviderIsolationKey(
            provider=route_key,
            profile=profile_name,
            model=model,
            base_url=base_url,
            proxy=proxy,
            tls_profile=tls_profile,
            credential_slot=credential_slot,
        )

    def get_or_build(
        self,
        profile_name: str,
        route_key: str,
        credential_slot: str,
        transport_tag: str,
        client: Any,
        call: Callable[..., Awaitable[Any]],
        *,
        supports_streaming: bool = False,
        stream_call: Optional[StreamCall] = None,
        deadline_budget_s: float = 30.0,
        force_rebuild: bool = False,
        model: str = "",
        base_url: str = "",
        proxy: str = "",
        tls_profile: str = "",
    ) -> ProviderRuntime:
        key = self._key(
            route_key,
            credential_slot,
            profile_name,
            model,
            base_url,
            proxy,
            tls_profile,
        )
        existing = self._runtimes.get(key)
        if existing is not None and not force_rebuild and existing.live:
            return existing
        if existing is not None:
            existing.shutdown()
        rt = ProviderRuntime(
            profile_name,
            route_key,
            credential_slot,
            transport_tag,
            client,
            call,
            supports_streaming=supports_streaming,
            stream_call=stream_call,
            deadline_budget_s=deadline_budget_s,
            isolation_key=key,
        )
        self._runtimes[key] = rt
        return rt

    def get(
        self,
        route_key: str,
        credential_slot: str,
        *,
        profile_name: Optional[str] = None,
        model: str = "",
        base_url: str = "",
        proxy: str = "",
        tls_profile: str = "",
    ) -> Optional[ProviderRuntime]:
        if profile_name is not None or any((model, base_url, proxy, tls_profile)):
            return self._runtimes.get(
                self._key(
                    route_key,
                    credential_slot,
                    profile_name or "",
                    model,
                    base_url,
                    proxy,
                    tls_profile,
                )
            )
        matches = [
            runtime
            for key, runtime in self._runtimes.items()
            if key.provider == route_key and key.credential_slot == credential_slot
        ]
        return matches[0] if len(matches) == 1 else None

    def shutdown(
        self,
        route_key: str,
        credential_slot: str,
        **identity: str,
    ) -> None:
        runtime = self.get(route_key, credential_slot, **identity)
        if runtime is None:
            return
        key = runtime.isolation_key
        self._runtimes.pop(key, None)
        runtime.shutdown()

    def shutdown_all(self) -> None:
        for runtime in list(self._runtimes.values()):
            runtime.shutdown()
        self._runtimes.clear()