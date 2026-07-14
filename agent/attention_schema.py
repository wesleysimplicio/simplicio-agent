"""Deterministic attention queue and bounded workspace selection.

The schema is mechanical: event content never controls priority and selection
does not invoke a model.  It publishes compact reasons, not private reasoning.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable


class AttentionReason(str, Enum):
    SAFETY = "safety"
    APPROVAL = "approval"
    FAILED_PRECONDITION = "failed_precondition"
    EFFECT_AMBIGUITY = "effect_ambiguity"
    BLOCKER = "blocker"
    GOAL_DRIFT = "goal_drift"
    BACKGROUND_COMPLETED = "background_completed"
    STALE_CRITICAL_BELIEF = "stale_critical_belief"
    USER_INTERVENTION = "user_intervention"
    DEADLINE_BUDGET = "deadline_budget"
    NORMAL_PROGRESS = "normal_progress"
    OPTIONAL_LEARNING = "optional_learning"


class AcknowledgementState(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


_PRIORITY = {reason: priority for priority, reason in enumerate(AttentionReason)}
_PREEMPTIVE = frozenset({AttentionReason.SAFETY, AttentionReason.APPROVAL})
_WORKSPACE_RECEIPT_SCHEMA = "simplicio.attention-workspace-receipt/v1"


@dataclass(frozen=True)
class AttentionItem:
    item_id: str
    source: str
    reason: AttentionReason
    expires_at: int
    run_id: str
    goal_id: str
    created_at: int
    relevance: int = 50
    provenance: str = "runtime"
    profile_id: str = "default"
    cause_receipts: tuple[str, ...] = ()
    cost: int = 1
    acknowledgement: AcknowledgementState = AcknowledgementState.OPEN
    priority: int = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "item_id",
            "source",
            "run_id",
            "goal_id",
            "provenance",
            "profile_id",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        object.__setattr__(self, "goal_id", self.goal_id.strip())
        if self.expires_at < self.created_at:
            raise ValueError("expires_at cannot precede created_at")
        if not 0 <= self.relevance <= 100:
            raise ValueError("relevance must be between 0 and 100")
        if self.cost < 1:
            raise ValueError("cost must be positive")
        object.__setattr__(self, "priority", _PRIORITY[self.reason])
        object.__setattr__(
            self, "cause_receipts", tuple(dict.fromkeys(self.cause_receipts))
        )

    @property
    def is_open(self) -> bool:
        return self.acknowledgement is AcknowledgementState.OPEN

    def close(self, state: AcknowledgementState, receipt: str) -> "AttentionItem":
        if state is AcknowledgementState.OPEN:
            raise ValueError("closing an attention item requires a terminal state")
        if not receipt.strip():
            raise ValueError(
                "completion, cancellation, or supersession requires a receipt"
            )
        return replace(
            self,
            acknowledgement=state,
            cause_receipts=tuple(dict.fromkeys((*self.cause_receipts, receipt))),
        )


@dataclass(frozen=True)
class WorkspaceReceipt:
    """Tamper-evident record of one goal-scoped workspace allocation."""

    goal_id: str
    selected_at: int
    budget: int
    used: int
    item_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        goal_id = self.goal_id.strip()
        if not goal_id:
            raise ValueError("goal_id must be non-empty")
        if self.budget < 1:
            raise ValueError("workspace budget must be positive")
        if not 0 <= self.used <= self.budget:
            raise ValueError("workspace used cost must fit within budget")
        if any(not item_id.strip() for item_id in self.item_ids):
            raise ValueError("workspace receipt item_ids must be non-empty")
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("workspace receipt item_ids must be unique")
        object.__setattr__(self, "goal_id", goal_id)

    @property
    def receipt_id(self) -> str:
        payload = json.dumps(
            self._payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            **self._payload(),
            "receipt_id": self.receipt_id,
        }

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _WORKSPACE_RECEIPT_SCHEMA,
            "goal_id": self.goal_id,
            "selected_at": self.selected_at,
            "budget": self.budget,
            "used": self.used,
            "item_ids": list(self.item_ids),
        }


@dataclass(frozen=True)
class WorkspaceSnapshot:
    items: tuple[AttentionItem, ...]
    budget: int
    used: int
    receipt: WorkspaceReceipt

    def explain(self) -> tuple[str, ...]:
        return tuple(
            f"{item.reason.value}: source={item.source}; run={item.run_id}"
            for item in self.items
        )


class AttentionQueue:
    """Queue with deterministic compaction and starvation-safe selection."""

    def __init__(self, items: Iterable[AttentionItem] = ()) -> None:
        self._items: dict[str, AttentionItem] = {}
        self._dedupe: dict[tuple[str, AttentionReason, str, str], str] = {}
        for item in items:
            self.publish(item)

    @property
    def items(self) -> tuple[AttentionItem, ...]:
        return tuple(self._items[key] for key in sorted(self._items))

    def publish(self, item: AttentionItem) -> AttentionItem:
        """Publish once; duplicate events merge causal receipts without storms."""
        key = (item.source, item.reason, item.run_id, item.goal_id)
        existing_id = self._dedupe.get(key)
        if existing_id is not None and self._items[existing_id].is_open:
            current = self._items[existing_id]
            merged = replace(
                current,
                cause_receipts=tuple(
                    dict.fromkeys((*current.cause_receipts, *item.cause_receipts))
                ),
                relevance=max(current.relevance, item.relevance),
                expires_at=max(current.expires_at, item.expires_at),
            )
            self._items[existing_id] = merged
            return merged
        self._items[item.item_id] = item
        if item.is_open:
            self._dedupe[key] = item.item_id
        return item

    def acknowledge(
        self, item_id: str, state: AcknowledgementState, receipt: str
    ) -> AttentionItem:
        closed = self._items[item_id].close(state, receipt)
        self._items[item_id] = closed
        self._dedupe.pop(
            (closed.source, closed.reason, closed.run_id, closed.goal_id), None
        )
        return closed

    def select_workspace(
        self, *, goal_id: str, budget: int, now: int
    ) -> WorkspaceSnapshot:
        goal_id = goal_id.strip()
        if not goal_id:
            raise ValueError("goal_id must be non-empty")
        if budget < 1:
            raise ValueError("workspace budget must be positive")
        candidates = [
            item
            for item in self._items.values()
            if item.is_open and item.goal_id == goal_id
        ]
        candidates.sort(key=lambda item: self._sort_key(item, now))

        chosen: list[AttentionItem] = []
        used = 0
        represented: set[tuple[str, str]] = set()

        # Preemptive items always lead; the remaining pass favors an unrepresented
        # profile/run before filling by score, preventing a busy run from starving peers.
        for phase in (True, False):
            remaining = [
                item
                for item in candidates
                if (item.reason in _PREEMPTIVE) is phase and item not in chosen
            ]
            while remaining:
                fair = [
                    item
                    for item in remaining
                    if (item.profile_id, item.run_id) not in represented
                ]
                item = (fair or remaining)[0]
                remaining.remove(item)
                if used + item.cost > budget:
                    continue
                chosen.append(item)
                used += item.cost
                represented.add((item.profile_id, item.run_id))

        receipt = WorkspaceReceipt(
            goal_id=goal_id,
            selected_at=now,
            budget=budget,
            used=used,
            item_ids=tuple(item.item_id for item in chosen),
        )
        return WorkspaceSnapshot(tuple(chosen), budget, used, receipt)

    @staticmethod
    def _sort_key(item: AttentionItem, now: int) -> tuple[int, int, str, str]:
        age = max(0, now - item.created_at)
        urgency = max(0, now - item.expires_at) + max(0, 20 - (item.expires_at - now))
        provenance = 10 if item.provenance in {"runtime", "human", "ledger"} else 0
        score = item.relevance + min(age, 100) + min(urgency, 100) + provenance
        return item.priority, -score, item.run_id, item.item_id
