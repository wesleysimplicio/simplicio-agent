"""Deterministic L0-L3 token routing for the native migration slice.

The governor is deliberately a pure, local policy object.  It decides whether
an intent can stay on a cache/deterministic/local path or must escalate to a
frontier provider; it never calls a provider and never stores prompt content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class GovernorLevel(str, Enum):
    L0 = "L0"  # cache / receipt hit
    L1 = "L1"  # deterministic local execution
    L2 = "L2"  # local guided interpretation
    L3 = "L3"  # frontier escalation


@dataclass(frozen=True)
class TurnBudget:
    """Independent input, output, and schema budgets for one route."""

    input_tokens: int
    output_tokens: int
    tool_schema_bytes: int

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.tool_schema_bytes) < 0:
            raise ValueError("turn budgets must be non-negative")

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_schema_bytes": self.tool_schema_bytes,
        }


DEFAULT_BUDGETS: Mapping[GovernorLevel, TurnBudget] = {
    GovernorLevel.L0: TurnBudget(0, 0, 0),
    GovernorLevel.L1: TurnBudget(0, 0, 0),
    GovernorLevel.L2: TurnBudget(1_024, 512, 1_024),
    GovernorLevel.L3: TurnBudget(2_000, 1_000, 1_024),
}


@dataclass(frozen=True)
class RouteReceipt:
    """Content-free evidence for one deterministic routing decision."""

    level: GovernorLevel
    intent_sha256: str
    budget: TurnBudget
    escalation_reason: str
    remote_tokens: int
    cache_hit: bool
    fallback: bool = False

    @property
    def remote_free(self) -> bool:
        return self.remote_tokens == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "intent_sha256": self.intent_sha256,
            "budget": self.budget.to_dict(),
            "escalation_reason": self.escalation_reason,
            "remote_tokens": self.remote_tokens,
            "cache_hit": self.cache_hit,
            "fallback": self.fallback,
            "remote_free": self.remote_free,
        }


def _intent_digest(intent: str) -> str:
    return hashlib.sha256(intent.encode("utf-8")).hexdigest()


class TokenGovernor:
    """Route intents using fixed entropy thresholds and safe local fallback."""

    def __init__(
        self,
        *,
        l1_entropy: float = 0.15,
        l2_entropy: float = 0.55,
        budgets: Mapping[GovernorLevel, TurnBudget] | None = None,
    ) -> None:
        if not 0 <= l1_entropy <= l2_entropy <= 1:
            raise ValueError("entropy thresholds must satisfy 0 <= L1 <= L2 <= 1")
        self.l1_entropy = l1_entropy
        self.l2_entropy = l2_entropy
        self.budgets = dict(budgets or DEFAULT_BUDGETS)
        missing = set(GovernorLevel) - set(self.budgets)
        if missing:
            raise ValueError(
                f"missing budgets for: {sorted(level.value for level in missing)}"
            )

    def route(
        self,
        intent: str,
        *,
        entropy: float = 0.0,
        cache_hit: bool = False,
        deterministic: bool = False,
        local_guidance: bool = True,
        remote_available: bool = True,
    ) -> RouteReceipt:
        """Return a route and budget without sending or logging raw intent text."""

        if not 0 <= entropy <= 1:
            raise ValueError("entropy must be between 0 and 1")
        reason = "cache-hit" if cache_hit else ""
        fallback = False
        if cache_hit:
            level = GovernorLevel.L0
        elif deterministic and entropy <= self.l1_entropy:
            level = GovernorLevel.L1
            reason = "deterministic-local"
        elif local_guidance and entropy <= self.l2_entropy:
            level = GovernorLevel.L2
            reason = "local-guided"
        elif remote_available:
            level = GovernorLevel.L3
            reason = (
                "entropy-escalation"
                if entropy > self.l2_entropy
                else "local-unavailable"
            )
        else:
            # Fail closed: unavailable frontier never causes a remote attempt.
            level = GovernorLevel.L1 if deterministic else GovernorLevel.L2
            reason = "frontier-unavailable-fallback"
            fallback = True

        budget = self.budgets[level]
        remote_tokens = (
            0
            if level is not GovernorLevel.L3
            else budget.input_tokens + budget.output_tokens
        )
        return RouteReceipt(
            level=level,
            intent_sha256=_intent_digest(intent),
            budget=budget,
            escalation_reason=reason,
            remote_tokens=remote_tokens,
            cache_hit=cache_hit,
            fallback=fallback,
        )

    def route_json(self, intent: str, **kwargs: Any) -> str:
        """Serialize a stable receipt for a ledger or fixture comparison."""

        return json.dumps(
            self.route(intent, **kwargs).to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )


__all__ = [
    "DEFAULT_BUDGETS",
    "GovernorLevel",
    "RouteReceipt",
    "TokenGovernor",
    "TurnBudget",
]
