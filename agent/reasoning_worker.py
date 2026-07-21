"""Deterministic-first adapter for the shared Agent runtime worker.

This module owns routing metadata only. ``AgentRuntimeContext`` remains the
sole executor for deterministic effects and reasoning work; this adapter does
not create a second queue, scheduler, process, or model client.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .protocol import AgentConversationResult
from .router.deterministic import DeterministicRouter, RouteDecision, default_router
from .runtime_context import AgentRuntimeContext

ROUTE_RECEIPT_SCHEMA = "simplicio.agent-route/v1"
RouteKind = Literal["deterministic", "local_reasoning", "frontier_reasoning", "ensemble", "blocked"]
Verification = Literal["PASS", "FAIL", "UNVERIFIED"]
DeterministicEffect = Callable[
    [dict[str, Any]], AgentConversationResult | Awaitable[AgentConversationResult]
]
ReasoningCall = Callable[[], AgentConversationResult | Awaitable[AgentConversationResult]]


@dataclass(frozen=True, slots=True)
class RouteReceipt:
    """Observable route evidence without synthetic token/cost accounting."""

    route: RouteKind
    reason: str
    confidence: float | None
    expected_tokens: int | None
    actual_tokens: int | None
    cache_hit: bool | None
    model: str | None
    backend: str | None
    escalation: str | None
    verification: Verification

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": ROUTE_RECEIPT_SCHEMA,
            "route": self.route,
            "reason": self.reason,
            "confidence": self.confidence,
            "expected_tokens": self.expected_tokens,
            "actual_tokens": self.actual_tokens,
            "cache_hit": self.cache_hit,
            "model": self.model,
            "backend": self.backend,
            "escalation": self.escalation,
            "verification": self.verification,
        }


@dataclass(frozen=True, slots=True)
class RoutePlan:
    decision: RouteDecision
    receipt: RouteReceipt


def _string_option(options: Mapping[str, Any], key: str) -> str | None:
    value = options.get(key)
    return value if isinstance(value, str) and value else None


def _verification(result: Mapping[str, Any]) -> Verification:
    if result.get("failed") is True or result.get("error"):
        return "FAIL"
    if result.get("completed") is True:
        return "PASS"
    return "UNVERIFIED"


def _with_receipt(
    result: AgentConversationResult | Mapping[str, Any], receipt: RouteReceipt
) -> AgentConversationResult:
    if not isinstance(result, Mapping):
        raise TypeError("agent result must be a mapping to carry a route receipt")
    enriched = dict(result)
    enriched["route_receipt"] = receipt.as_dict()
    return enriched  # type: ignore[return-value]


class SharedReasoningWorker:
    """Route work into the already-shared :class:`AgentRuntimeContext`.

    The worker is an adapter, not a scheduler. Every branch calls
    ``runtime.submit`` and inherits Runtime backpressure, cancellation,
    lifecycle, and Loop Hub progress/result receipts.
    """

    def __init__(
        self,
        runtime: AgentRuntimeContext,
        *,
        router: DeterministicRouter | None = None,
        deterministic_effect: DeterministicEffect | None = None,
    ) -> None:
        self.runtime = runtime
        self.router = router or default_router()
        self.deterministic_effect = deterministic_effect

    def plan(
        self, message: str, *, conversation_kwargs: Mapping[str, Any] | None = None
    ) -> RoutePlan:
        options = conversation_kwargs or {}
        decision = self.router.route(message)
        model = _string_option(options, "model")
        backend = _string_option(options, "backend")
        if decision.answer is not None:
            receipt = RouteReceipt(
                route="deterministic",
                reason=f"deterministic intent: {decision.intent}",
                confidence=1.0,
                expected_tokens=0,
                actual_tokens=0,
                cache_hit=None,
                model=model,
                backend=backend,
                escalation=None,
                verification="PASS",
            )
        elif decision.tool_call is not None and self.deterministic_effect is None:
            receipt = RouteReceipt(
                route="blocked",
                reason="deterministic effect requires an explicit Runtime gate",
                confidence=1.0,
                expected_tokens=0,
                actual_tokens=0,
                cache_hit=None,
                model=model,
                backend=backend,
                escalation=None,
                verification="UNVERIFIED",
            )
        elif decision.tool_call is not None:
            receipt = RouteReceipt(
                route="deterministic",
                reason=f"deterministic intent delegated to Runtime gate: {decision.intent}",
                confidence=1.0,
                expected_tokens=0,
                actual_tokens=0,
                cache_hit=None,
                model=model,
                backend=backend,
                escalation=None,
                verification="UNVERIFIED",
            )
        else:
            receipt = RouteReceipt(
                route="frontier_reasoning",
                reason="deterministic router miss; delegate to the shared Agent worker",
                confidence=None,
                expected_tokens=None,
                actual_tokens=None,
                cache_hit=None,
                model=model,
                backend=backend,
                escalation=None,
                verification="UNVERIFIED",
            )
        return RoutePlan(decision=decision, receipt=receipt)

    async def submit(
        self,
        *,
        task_id: str | None,
        key: str | None,
        payload: dict[str, Any],
        message: str,
        conversation_kwargs: Mapping[str, Any],
        reasoning: ReasoningCall,
        plan: RoutePlan | None = None,
    ) -> Any:
        plan = plan or self.plan(message, conversation_kwargs=conversation_kwargs)
        receipt = plan.receipt
        runtime_payload = dict(payload)
        runtime_payload["route_receipt"] = receipt.as_dict()

        async def execute() -> AgentConversationResult:
            if receipt.route == "deterministic" and plan.decision.answer is not None:
                return {
                    "final_response": plan.decision.answer,
                    "messages": [],
                    "api_calls": 0,
                    "completed": True,
                    "failed": False,
                    "route_receipt": receipt.as_dict(),
                }
            if receipt.route == "blocked":
                return {
                    "final_response": None,
                    "messages": [],
                    "api_calls": 0,
                    "completed": False,
                    "failed": True,
                    "error": receipt.reason,
                    "route_receipt": receipt.as_dict(),
                }
            if plan.decision.tool_call is not None:
                assert self.deterministic_effect is not None
                value = self.deterministic_effect(plan.decision.tool_call)
            else:
                value = reasoning()
            value = await value if inspect.isawaitable(value) else value
            if not isinstance(value, Mapping):
                raise TypeError("Runtime gate and Agent must return a mapping")
            verified = RouteReceipt(
                route=receipt.route,
                reason=receipt.reason,
                confidence=receipt.confidence,
                expected_tokens=receipt.expected_tokens,
                actual_tokens=receipt.actual_tokens,
                cache_hit=receipt.cache_hit,
                model=receipt.model,
                backend=receipt.backend,
                escalation=receipt.escalation,
                verification=_verification(value),
            )
            return _with_receipt(value, verified)

        return await self.runtime.submit(
            execute,
            task_id=task_id,
            key=key,
            payload=runtime_payload,
        )


__all__ = ["ROUTE_RECEIPT_SCHEMA", "RoutePlan", "RouteReceipt", "SharedReasoningWorker"]
