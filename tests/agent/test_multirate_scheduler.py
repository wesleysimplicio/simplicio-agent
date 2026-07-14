from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.multirate_scheduler import (
    MULTIRATE_SCHEDULER_SCHEMA,
    DispatchDecision,
    EnqueueStatus,
    LaneName,
    MultiRateScheduler,
    MultiRateSchedulerConfig,
    QueueEventKind,
    WorkItem,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "multirate" / "bounded_contract.json"
)


def _load_scheduler() -> MultiRateScheduler:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    config = MultiRateSchedulerConfig.from_dict(payload)
    return MultiRateScheduler(config)


def _decision_or_fail(value: DispatchDecision | None) -> DispatchDecision:
    assert value is not None
    return value


def test_fixture_round_trip_exposes_expected_schema_and_all_lanes():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    config = MultiRateSchedulerConfig.from_dict(payload)
    assert config.schema_version == MULTIRATE_SCHEDULER_SCHEMA
    assert config.to_dict() == payload
    assert tuple(config.lanes) == (
        LaneName.EVENT,
        LaneName.REFLEX,
        LaneName.ATTENTION,
        LaneName.DELIBERATION,
        LaneName.CONSOLIDATION,
    )


def test_event_ownership_replaces_stale_work_for_same_owner_and_lane():
    scheduler = _load_scheduler()
    first = scheduler.enqueue(WorkItem(owner="chat:1", lane=LaneName.EVENT, payload="old"))
    second = scheduler.enqueue(WorkItem(owner="chat:1", lane=LaneName.EVENT, payload="new"))
    decision = _decision_or_fail(scheduler.tick())
    assert first.status is EnqueueStatus.ACCEPTED
    assert second.status is EnqueueStatus.REPLACED
    assert decision.payload == "new"
    assert decision.owner == "chat:1"


def test_bounded_queue_rejects_new_owner_with_explicit_backpressure():
    scheduler = _load_scheduler()
    assert scheduler.enqueue(WorkItem(owner="a", lane=LaneName.EVENT, payload="1")).status is EnqueueStatus.ACCEPTED
    assert scheduler.enqueue(WorkItem(owner="b", lane=LaneName.EVENT, payload="2")).status is EnqueueStatus.ACCEPTED
    rejected = scheduler.enqueue(WorkItem(owner="c", lane=LaneName.EVENT, payload="3"))
    assert rejected.status is EnqueueStatus.REJECTED_BACKPRESSURE
    assert rejected.reason == "lane_queue_full"


def test_token_budget_exhaustion_escalates_from_reflex_to_attention():
    scheduler = _load_scheduler()
    scheduler.enqueue(
        WorkItem(owner="chat:2", lane=LaneName.REFLEX, payload="expensive", token_cost=5)
    )
    assert scheduler.tick() is None
    assert scheduler.snapshot()["queues"]["reflex"] == 0
    assert scheduler.snapshot()["queues"]["attention"] == 1
    assert scheduler.event_log[-1].kind is QueueEventKind.ESCALATED
    decision = _decision_or_fail(scheduler.tick())
    assert decision.lane is LaneName.ATTENTION
    assert decision.metadata["escalated_from"] == LaneName.REFLEX.value


def test_resource_budget_exhaustion_escalates_and_preserves_cost():
    scheduler = _load_scheduler()
    scheduler.enqueue(
        WorkItem(
            owner="chat:resource",
            lane=LaneName.REFLEX,
            payload="provider-work",
            resource_cost=3,
        )
    )
    assert scheduler.tick() is None
    assert scheduler.snapshot()["queues"]["reflex"] == 0
    assert scheduler.snapshot()["queues"]["attention"] == 1
    assert scheduler.event_log[-1].reason == "resource_budget_exceeded"

    decision = _decision_or_fail(scheduler.tick())
    assert decision.lane is LaneName.ATTENTION
    assert decision.resource_cost == 3
    assert scheduler.snapshot()["remaining_resources"]["attention"] == 5


def test_dispatch_debits_token_and_resource_budgets_together():
    scheduler = _load_scheduler()
    scheduler.enqueue(
        WorkItem(
            owner="chat:budget",
            lane=LaneName.EVENT,
            payload="bounded-work",
            token_cost=2,
            resource_cost=2,
        )
    )
    decision = _decision_or_fail(scheduler.tick())
    snapshot = scheduler.snapshot()
    assert decision.token_cost == 2
    assert decision.resource_cost == 2
    assert snapshot["remaining_tokens"]["event"] == 0
    assert snapshot["remaining_resources"]["event"] == 0


def test_latency_budget_exceeded_escalates_to_slower_lane():
    scheduler = _load_scheduler()
    scheduler.enqueue(WorkItem(owner="chat:3", lane=LaneName.ATTENTION, payload="slow"))
    scheduler.tick()
    decision = _decision_or_fail(scheduler.tick())
    assert any(
        event.kind is QueueEventKind.ESCALATED
        and event.reason == "latency_budget_exceeded"
        and event.target_lane is LaneName.DELIBERATION
        for event in scheduler.event_log
    )
    assert decision.lane is LaneName.DELIBERATION
    assert decision.metadata["escalated_from"] == LaneName.ATTENTION.value


def test_aging_prevents_starvation_even_against_higher_priority_reflex_work():
    scheduler = _load_scheduler()
    scheduler.enqueue(
        WorkItem(owner="archive", lane=LaneName.CONSOLIDATION, payload="compress-history")
    )
    for index in range(7):
        scheduler.enqueue(
            WorkItem(
                owner=f"reflex:{index}",
                lane=LaneName.REFLEX,
                payload=f"r{index}",
            )
        )
        scheduler.tick()
    decision = _decision_or_fail(scheduler.tick())
    assert decision.lane is LaneName.CONSOLIDATION
    assert decision.owner == "archive"


def test_slow_lane_failure_is_quarantined_and_fast_lanes_keep_dispatching():
    scheduler = _load_scheduler()
    scheduler.enqueue(
        WorkItem(owner="analysis", lane=LaneName.DELIBERATION, payload="deep-think")
    )
    scheduler.enqueue(WorkItem(owner="chat:4", lane=LaneName.EVENT, payload="interrupt"))
    event_decision = _decision_or_fail(scheduler.tick())
    assert event_decision.lane is LaneName.EVENT
    deliberation_decision = _decision_or_fail(scheduler.tick())
    assert deliberation_decision.lane is LaneName.DELIBERATION
    failure = scheduler.fail(deliberation_decision, reason="planner crashed")
    assert failure.kind is QueueEventKind.FAILED
    assert scheduler.snapshot()["queues"]["consolidation"] == 1
    scheduler.enqueue(WorkItem(owner="chat:5", lane=LaneName.EVENT, payload="next"))
    follow_up = _decision_or_fail(scheduler.tick())
    assert follow_up.lane is LaneName.EVENT
    assert follow_up.owner == "chat:5"


def test_final_lane_drop_is_recorded_when_no_escalation_target_exists():
    scheduler = _load_scheduler()
    scheduler.enqueue(
        WorkItem(
            owner="history",
            lane=LaneName.CONSOLIDATION,
            payload="too-costly",
            token_cost=50,
        )
    )
    assert scheduler.tick() is None
    assert scheduler.failure_log[-1].kind is QueueEventKind.DROPPED
    assert scheduler.failure_log[-1].reason == "token_budget_exceeded"
