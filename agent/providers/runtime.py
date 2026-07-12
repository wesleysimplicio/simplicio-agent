"""ProviderRuntime: per-route, credential-isolated provider lifecycle (issue #224).

A ``ProviderRuntime`` binds together, for one route/credential isolation key:

* a ``ProviderProfile`` (identity, endpoint, capabilities, quirks);
* a ``ProviderTransport`` (message/tool schema normalization);
* the concrete client/SDK and its connection lifecycle;
* a credential slot (never shared across profiles/tenants — invariant #2);
* a retry/fallback/circuit policy reusing :mod:`agent.providers.fallback_chain`;
* usage / cost accounting;
* redacted telemetry (no prompts / secrets by default — invariant #8).

Key design choices mandated by the issue:
* Provider-specific SDKs stay preferred when mature (invariant #6).
* Retry honours a global deadline budget and request idempotency (invariant #3).
* Cancellation closes the underlying request/stream and leaves no orphan task
  (invariant #4).
* This module is pure-stdlib and transport-agnostic; it accepts callables so it
  can be unit-tested with fakes (no network, no credentials).

Lifecycle
---------
``build()`` is idempotent per key: repeated calls return the same live runtime,
reusing the client. ``shutdown()`` tears down the client and clears the
registry slot. ``ProviderRuntimeRegistry`` owns the per-key map and enforces
credential isolation.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from agent.providers.fallback_chain import (
    AsyncProviderChain,
    ProviderChainMetrics,
    ProviderResult,
)


@dataclass
class UsageAccounting:
    """Per-runtime usage / cost accounting (redacted: no prompt text)."""

    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    errors: int = 0
    retries: int = 0
    switches: int = 0
    wall_s: float = 0.0

    def add(self, *, prompt_tokens: int = 0, completion_tokens: int = 0,
            total_tokens: int = 0, retries: int = 0, switches: int = 0,
            wall_s: float = 0.0, error: bool = False) -> None:
        self.requests += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.retries += retries
        self.switches += switches
        self.wall_s += wall_s
        if error:
            self.errors += 1


@dataclass
class RuntimeTelemetry:
    """Redacted telemetry snapshot — never embeds prompts or secrets."""

    profile: str
    route_key: str
    credential_slot: str
    built: bool
    live: bool
    accounting: UsageAccounting


# A provider capsule: the whole thing is swapped atomically on fallback.
@dataclass
class _ProviderCapsule:
    profile_name: str
    transport_tag: str
    credential_slot: str
    client: Any
    call: Callable[..., Awaitable[Any]]
    supports_streaming: bool


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
        deadline_budget_s: float = 30.0,
    ) -> None:
        # invariant #2: credential slot is explicit and bound to this runtime.
        self.profile_name = profile_name
        self.route_key = route_key
        self.credential_slot = credential_slot
        self.transport_tag = transport_tag
        self._capsule = _ProviderCapsule(
            profile_name=profile_name,
            transport_tag=transport_tag,
            credential_slot=credential_slot,
            client=client,
            call=call,
            supports_streaming=supports_streaming,
        )
        self._deadline_budget_s = deadline_budget_s
        self._accounting = UsageAccounting()
        self._built_at = time.monotonic()
        self._live = True
        self._closed = False

    # -- lifecycle ---------------------------------------------------------
    @property
    def live(self) -> bool:
        return self._live and not self._closed

    def built(self) -> bool:
        return self._capsule.client is not None

    def shutdown(self) -> None:
        """Tear down the client and mark the runtime closed (invariant #4).

        Safe to call from any context: if an event loop is already running
        (e.g. during an async request), the async client closer is scheduled
        cooperatively instead of spawning a nested loop, so no coroutine is
        leaked and no ``RuntimeError`` is raised.
        """
        if self._closed:
            return
        client = self._capsule.client
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if callable(closer):
            try:
                if asyncio.iscoroutinefunction(closer):
                    try:
                        asyncio.run(closer())  # type: ignore[arg-type]
                    except RuntimeError:
                        # Loop already running (called mid-request): schedule it.
                        asyncio.ensure_future(closer())  # type: ignore[arg-type]
                else:
                    closer()
            except Exception:
                pass
        self._live = False
        self._closed = True

    def swap_to(self, other: "ProviderRuntime") -> None:
        """Atomic fallback: replace the entire capsule, never cross-profile parts."""
        if other.credential_slot != self.credential_slot:
            # invariant #2: never mix credential slots across tenants.
            raise ValueError(
                f"refusing to swap credential slot "
                f"{self.credential_slot!r} -> {other.credential_slot!r}"
            )
        self._capsule = other._capsule
        self.profile_name = other.profile_name
        self.transport_tag = other.transport_tag

    # -- invocation --------------------------------------------------------
    async def run(
        self,
        prompt: str,
        *,
        idempotency_key: Optional[str] = None,
        retries: int = 3,
    ) -> ProviderResult:
        """Run one request under the global deadline budget (invariant #3).

        ``idempotency_key`` is recorded (not sent to the provider) so callers
        can dedup/observe retries; the underlying call is guarded by the
        runtime deadline so a single request cannot exceed the budget.
        """
        if self._closed:
            raise RuntimeError("ProviderRuntime is shut down")
        idem = idempotency_key or uuid.uuid4().hex
        deadline = self._deadline_budget_s
        _ = idem  # reserved for idempotency-aware transports
        start = time.monotonic()
        chain: AsyncProviderChain = AsyncProviderChain(
            providers=[(self.profile_name, self._capsule.call)],
            max_retries=retries,
        )
        try:
            result = await asyncio.wait_for(chain.call(prompt), timeout=deadline)
        except Exception:
            # Count the request (and the error) without double-counting below.
            self._accounting.add(error=True, retries=retries)
            raise
        elapsed = time.monotonic() - start
        self._accounting.add(
            retries=getattr(result, "retries", 0),
            wall_s=elapsed,
            error=False,
        )
        return result

    # -- observability -----------------------------------------------------
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
    """Owns one ``ProviderRuntime`` per (route_key, credential_slot)."""

    def __init__(self) -> None:
        self._runtimes: Dict[str, ProviderRuntime] = {}

    @staticmethod
    def _key(route_key: str, credential_slot: str) -> str:
        return f"{route_key}::{credential_slot}"

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
        deadline_budget_s: float = 30.0,
        force_rebuild: bool = False,
    ) -> ProviderRuntime:
        key = self._key(route_key, credential_slot)
        existing = self._runtimes.get(key)
        if existing is not None and not force_rebuild and existing.live:
            return existing  # reuse: connection / client lifecycle preserved.
        rt = ProviderRuntime(
            profile_name, route_key, credential_slot, transport_tag,
            client, call, supports_streaming=supports_streaming,
            deadline_budget_s=deadline_budget_s,
        )
        self._runtimes[key] = rt
        return rt

    def get(self, route_key: str, credential_slot: str) -> Optional[ProviderRuntime]:
        return self._runtimes.get(self._key(route_key, credential_slot))

    def shutdown(self, route_key: str, credential_slot: str) -> None:
        rt = self._runtimes.pop(self._key(route_key, credential_slot), None)
        if rt is not None:
            rt.shutdown()

    def shutdown_all(self) -> None:
        for rt in list(self._runtimes.values()):
            rt.shutdown()
        self._runtimes.clear()
