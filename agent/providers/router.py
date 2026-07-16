"""Provider-agnostic local-first router built on the existing fallback policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from agent.providers.fallback_chain import (
    AsyncProviderChain,
    AsyncProviderCallable,
    ProviderCallable,
    ProviderChain,
    ProviderChainMetrics,
    ProviderResult,
)

Availability = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """A provider-independent route descriptor."""

    name: str
    kind: str
    call: ProviderCallable
    available: Availability = lambda: True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("provider route name must be non-empty")
        if self.kind not in {"local", "remote"}:
            raise ValueError("provider route kind must be local or remote")


@dataclass
class ProviderRouter:
    """Try available local routes first, then use bounded provider fallback."""

    routes: Sequence[ProviderRoute] = ()
    prefer_local: bool = True
    max_retries: int = 3
    metrics: ProviderChainMetrics = field(default_factory=ProviderChainMetrics)

    def ordered_routes(self) -> tuple[ProviderRoute, ...]:
        available = [route for route in self.routes if route.available()]
        if self.prefer_local:
            available.sort(key=lambda route: (route.kind != "local", route.name))
        return tuple(available)

    def call(self, prompt: str) -> ProviderResult:
        routes = self.ordered_routes()
        if not routes:
            raise RuntimeError("ProviderRouter has no available providers")
        chain = ProviderChain(
            providers=tuple((route.name, route.call) for route in routes),
            max_retries=self.max_retries,
            metrics=self.metrics,
        )
        return chain.call(prompt)

    def health(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {"name": route.name, "kind": route.kind, "available": bool(route.available())}
            for route in self.routes
        )


@dataclass
class AsyncProviderRouter:
    """Async counterpart with the same local-first ordering contract."""

    routes: Sequence[tuple[str, str, AsyncProviderCallable, Availability]] = ()
    prefer_local: bool = True
    max_retries: int = 3
    metrics: ProviderChainMetrics = field(default_factory=ProviderChainMetrics)

    def _ordered(self) -> tuple[tuple[str, str, AsyncProviderCallable, Availability], ...]:
        available = [route for route in self.routes if route[3]()]
        if self.prefer_local:
            available.sort(key=lambda route: (route[1] != "local", route[0]))
        return tuple(available)

    async def call(self, prompt: str) -> ProviderResult:
        routes = self._ordered()
        if not routes:
            raise RuntimeError("AsyncProviderRouter has no available providers")
        chain = AsyncProviderChain(
            providers=tuple((route[0], route[2]) for route in routes),
            max_retries=self.max_retries,
            metrics=self.metrics,
        )
        return await chain.call(prompt)


__all__ = ["AsyncProviderRouter", "ProviderRoute", "ProviderRouter"]
