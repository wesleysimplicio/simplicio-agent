"""Deterministic multi-rate scheduler contract for bounded agent lanes.

This module intentionally stays isolated from production conversation loops.
It models the queueing, dispatch, budget, and escalation rules needed for a
bounded multi-rate scheduler so the contract can be tested before wiring.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


MULTIRATE_SCHEDULER_SCHEMA = "simplicio.multirate-scheduler/v1"


class LaneName(str, Enum):
    EVENT = "event"
    REFLEX = "reflex"
    ATTENTION = "attention"
    DELIBERATION = "deliberation"
    CONSOLIDATION = "consolidation"


LANE_ORDER: tuple[LaneName, ...] = (
    LaneName.EVENT,
    LaneName.REFLEX,
    LaneName.ATTENTION,
    LaneName.DELIBERATION,
    LaneName.CONSOLIDATION,
)

SLOW_LANES = frozenset({LaneName.DELIBERATION, LaneName.CONSOLIDATION})


class EnqueueStatus(str, Enum):
    ACCEPTED = "accepted"
    REPLACED = "replaced"
    REJECTED_BACKPRESSURE = "rejected_backpressure"


class QueueEventKind(str, Enum):
    DISPATCHED = "dispatched"
    ESCALATED = "escalated"
    FAILED = "failed"
    DROPPED = "dropped"


@dataclass(frozen=True)
class LaneConfig:
    """Deterministic budget and cadence settings for one lane."""

    cadence_ticks: int
    max_queue: int
    latency_budget_ticks: int
    token_budget: int
    base_priority: int
    starvation_window_ticks: int = 1
    escalation_target: LaneName | None = None

    def __post_init__(self) -> None:
        if self.cadence_ticks < 1:
            raise ValueError("cadence_ticks must be >= 1")
        if self.max_queue < 1:
            raise ValueError("max_queue must be >= 1")
        if self.latency_budget_ticks < 1:
            raise ValueError("latency_budget_ticks must be >= 1")
        if self.token_budget < 1:
            raise ValueError("token_budget must be >= 1")
        if self.starvation_window_ticks < 1:
            raise ValueError("starvation_window_ticks must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "cadence_ticks": self.cadence_ticks,
            "max_queue": self.max_queue,
            "latency_budget_ticks": self.latency_budget_ticks,
            "token_budget": self.token_budget,
            "base_priority": self.base_priority,
            "starvation_window_ticks": self.starvation_window_ticks,
        }
        if self.escalation_target is not None:
            result["escalation_target"] = self.escalation_target.value
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LaneConfig":
        target = value.get("escalation_target")
        return cls(
            cadence_ticks=int(value["cadence_ticks"]),
            max_queue=int(value["max_queue"]),
            latency_budget_ticks=int(value["latency_budget_ticks"]),
            token_budget=int(value["token_budget"]),
            base_priority=int(value["base_priority"]),
            starvation_window_ticks=int(value.get("starvation_window_ticks", 1)),
            escalation_target=LaneName(target) if target else None,
        )


@dataclass(frozen=True)
class MultiRateSchedulerConfig:
    """Versioned config describing the bounded scheduler contract."""

    lanes: dict[LaneName, LaneConfig]
    schema_version: str = MULTIRATE_SCHEDULER_SCHEMA

    def __post_init__(self) -> None:
        missing = [lane for lane in LANE_ORDER if lane not in self.lanes]
        if missing:
            raise ValueError(f"missing lane configs: {', '.join(lane.value for lane in missing)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lanes": {
                lane.value: self.lanes[lane].to_dict()
                for lane in LANE_ORDER
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MultiRateSchedulerConfig":
        raw_lanes = value.get("lanes")
        if not isinstance(raw_lanes, Mapping):
            raise ValueError("lanes must be an object")
        lanes = {
            LaneName(name): LaneConfig.from_dict(config)
            for name, config in raw_lanes.items()
        }
        return cls(
            schema_version=str(value.get("schema_version", MULTIRATE_SCHEDULER_SCHEMA)),
            lanes=lanes,
        )


@dataclass(frozen=True)
class WorkItem:
    """Immutable work descriptor owned by an event source or logical actor."""

    owner: str
    lane: LaneName
    payload: str
    token_cost: int = 1
    priority_boost: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.owner.strip():
            raise ValueError("owner must be non-empty")
        if not self.payload.strip():
            raise ValueError("payload must be non-empty")
        if self.token_cost < 1:
            raise ValueError("token_cost must be >= 1")


@dataclass(frozen=True)
class EnqueueResult:
    status: EnqueueStatus
    lane: LaneName
    owner: str
    reason: str = ""
    replaced: bool = False


@dataclass(frozen=True)
class QueueEvent:
    kind: QueueEventKind
    owner: str
    lane: LaneName
    tick: int
    reason: str = ""
    target_lane: LaneName | None = None


@dataclass(frozen=True)
class DispatchDecision:
    owner: str
    lane: LaneName
    payload: str
    token_cost: int
    tick: int
    waited_ticks: int
    effective_priority: int
    metadata: Mapping[str, Any]


@dataclass
class _QueuedItem:
    work: WorkItem
    enqueued_tick: int
    sequence: int


class MultiRateScheduler:
    """Mutable bounded scheduler with deterministic selection rules."""

    def __init__(self, config: MultiRateSchedulerConfig):
        self.config = config
        self.current_tick = 0
        self._sequence = 0
        self._queues: dict[LaneName, OrderedDict[str, _QueuedItem]] = {
            lane: OrderedDict() for lane in LANE_ORDER
        }
        self._remaining_tokens: dict[LaneName, int] = {
            lane: config.lanes[lane].token_budget for lane in LANE_ORDER
        }
        self._last_budget_reset_tick = 0
        self.event_log: list[QueueEvent] = []
        self.failure_log: list[QueueEvent] = []

    def snapshot(self) -> dict[str, Any]:
        return {
            "tick": self.current_tick,
            "queues": {
                lane.value: len(self._queues[lane])
                for lane in LANE_ORDER
            },
            "remaining_tokens": {
                lane.value: self._remaining_tokens[lane]
                for lane in LANE_ORDER
            },
            "event_log_size": len(self.event_log),
            "failure_log_size": len(self.failure_log),
        }

    def enqueue(self, work: WorkItem, *, tick: int | None = None) -> EnqueueResult:
        queue = self._queues[work.lane]
        now = self.current_tick if tick is None else tick
        existing = queue.get(work.owner)
        if existing is not None:
            queue[work.owner] = _QueuedItem(work=work, enqueued_tick=now, sequence=existing.sequence)
            return EnqueueResult(
                status=EnqueueStatus.REPLACED,
                lane=work.lane,
                owner=work.owner,
                reason="owner_slot_replaced",
                replaced=True,
            )
        if len(queue) >= self.config.lanes[work.lane].max_queue:
            return EnqueueResult(
                status=EnqueueStatus.REJECTED_BACKPRESSURE,
                lane=work.lane,
                owner=work.owner,
                reason="lane_queue_full",
            )
        self._sequence += 1
        queue[work.owner] = _QueuedItem(work=work, enqueued_tick=now, sequence=self._sequence)
        return EnqueueResult(
            status=EnqueueStatus.ACCEPTED,
            lane=work.lane,
            owner=work.owner,
        )

    def tick(self) -> DispatchDecision | None:
        self.current_tick += 1
        self._reset_budgets_for_tick()
        return self._dispatch_ready()

    def fail(self, decision: DispatchDecision, *, reason: str) -> QueueEvent:
        event = QueueEvent(
            kind=QueueEventKind.FAILED,
            owner=decision.owner,
            lane=decision.lane,
            tick=self.current_tick,
            reason=reason,
        )
        self.failure_log.append(event)
        if decision.lane in SLOW_LANES:
            self._escalate_work(
                WorkItem(
                    owner=decision.owner,
                    lane=decision.lane,
                    payload=decision.payload,
                    token_cost=decision.token_cost,
                    metadata=decision.metadata,
                ),
                from_lane=decision.lane,
                reason=f"slow_lane_failure:{reason}",
            )
        return event

    def _reset_budgets_for_tick(self) -> None:
        if self._last_budget_reset_tick == self.current_tick:
            return
        for lane in LANE_ORDER:
            self._remaining_tokens[lane] = self.config.lanes[lane].token_budget
        self._last_budget_reset_tick = self.current_tick

    def _dispatch_ready(self) -> DispatchDecision | None:
        for _ in range(sum(len(queue) for queue in self._queues.values()) + 1):
            candidate = self._next_candidate()
            if candidate is None:
                return None
            lane, owner, queued = candidate
            lane_config = self.config.lanes[lane]
            waited_ticks = self.current_tick - queued.enqueued_tick
            if waited_ticks > lane_config.latency_budget_ticks:
                if self._escalate_work(queued.work, from_lane=lane, reason="latency_budget_exceeded"):
                    del self._queues[lane][owner]
                    continue
            if queued.work.token_cost > self._remaining_tokens[lane]:
                if self._escalate_work(queued.work, from_lane=lane, reason="token_budget_exceeded"):
                    del self._queues[lane][owner]
                    continue
                self._record_drop(queued.work, lane=lane, reason="token_budget_exceeded")
                del self._queues[lane][owner]
                continue
            del self._queues[lane][owner]
            self._remaining_tokens[lane] -= queued.work.token_cost
            decision = DispatchDecision(
                owner=queued.work.owner,
                lane=lane,
                payload=queued.work.payload,
                token_cost=queued.work.token_cost,
                tick=self.current_tick,
                waited_ticks=waited_ticks,
                effective_priority=self._effective_priority(lane, queued),
                metadata=queued.work.metadata,
            )
            self.event_log.append(
                QueueEvent(
                    kind=QueueEventKind.DISPATCHED,
                    owner=decision.owner,
                    lane=decision.lane,
                    tick=self.current_tick,
                )
            )
            return decision
        return None

    def _next_candidate(self) -> tuple[LaneName, str, _QueuedItem] | None:
        best: tuple[int, int, int, int, LaneName, str, _QueuedItem] | None = None
        for lane_index, lane in enumerate(LANE_ORDER):
            lane_config = self.config.lanes[lane]
            if self.current_tick % lane_config.cadence_ticks != 0:
                continue
            for owner, queued in self._queues[lane].items():
                age = self.current_tick - queued.enqueued_tick
                effective_priority = self._effective_priority(lane, queued)
                key = (
                    effective_priority,
                    age,
                    -queued.sequence,
                    -lane_index,
                    lane,
                    owner,
                    queued,
                )
                if best is None or key > best:
                    best = key
        if best is None:
            return None
        return best[4], best[5], best[6]

    def _effective_priority(self, lane: LaneName, queued: _QueuedItem) -> int:
        config = self.config.lanes[lane]
        age = self.current_tick - queued.enqueued_tick
        aging_bonus = age // config.starvation_window_ticks
        return config.base_priority + queued.work.priority_boost + aging_bonus

    def _escalate_work(
        self,
        work: WorkItem,
        *,
        from_lane: LaneName,
        reason: str,
    ) -> bool:
        target = self.config.lanes[from_lane].escalation_target
        if target is None:
            self._record_drop(work, lane=from_lane, reason=reason)
            return False
        result = self.enqueue(
            WorkItem(
                owner=work.owner,
                lane=target,
                payload=work.payload,
                token_cost=work.token_cost,
                priority_boost=work.priority_boost,
                metadata=dict(work.metadata, escalated_from=from_lane.value, escalation_reason=reason),
            ),
            tick=self.current_tick,
        )
        if result.status is EnqueueStatus.REJECTED_BACKPRESSURE:
            self._record_drop(work, lane=from_lane, reason=f"{reason}:target_full")
            return False
        self.event_log.append(
            QueueEvent(
                kind=QueueEventKind.ESCALATED,
                owner=work.owner,
                lane=from_lane,
                tick=self.current_tick,
                reason=reason,
                target_lane=target,
            )
        )
        return True

    def _record_drop(self, work: WorkItem, *, lane: LaneName, reason: str) -> None:
        self.failure_log.append(
            QueueEvent(
                kind=QueueEventKind.DROPPED,
                owner=work.owner,
                lane=lane,
                tick=self.current_tick,
                reason=reason,
            )
        )
