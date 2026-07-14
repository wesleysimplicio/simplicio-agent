"""Focused contract tests for issue #155 persistent runs."""

import pytest

from agent.persistent_run import (
    CompletionNotReady,
    DuplicateCommittedEffect,
    InvalidRunTransition,
    PersistentRun,
    PersistentRunError,
    RunEffect,
    RunEffectStatus,
    RunState,
)


def _run() -> PersistentRun:
    return PersistentRun.create(
        run_id="run-1",
        goal_hash="sha256:goal",
        phase="plan",
        step="first",
        budgets={"tokens": 1000, "wall_ms": 5000},
        leases=["lease-1"],
        provider_state={"provider": "local", "version": "1"},
        now_ns=10,
    )


def test_lifecycle_is_explicit_and_same_state_is_idempotent():
    run = _run()
    assert run.transition(RunState.PLANNED, now_ns=10) is run
    run = run.transition(RunState.QUEUED, now_ns=11).transition(
        RunState.RUNNING, now_ns=12
    )
    run = run.transition(RunState.PAUSED, now_ns=13).transition(
        RunState.QUEUED, now_ns=14
    )
    assert run.state is RunState.QUEUED
    with pytest.raises(InvalidRunTransition):
        run.transition(RunState.COMPLETED, now_ns=15)


def test_completion_requires_receipt_and_no_unresolved_effect():
    run = (
        _run()
        .transition(RunState.QUEUED, now_ns=11)
        .transition(RunState.RUNNING, now_ns=12)
    )
    run = run.record_effect(
        RunEffect("effect-1", "idempotency-1", RunEffectStatus.UNKNOWN), now_ns=13
    )
    run = run.add_receipt("receipt://run-1/goal", now_ns=14)
    with pytest.raises(CompletionNotReady):
        run.transition(RunState.COMPLETED, now_ns=15)
    run = run.record_effect(
        RunEffect(
            "effect-1",
            "idempotency-1",
            RunEffectStatus.RECONCILED,
            "receipt://run-1/effect-1",
        ),
        now_ns=16,
    )
    assert run.transition(RunState.COMPLETED, now_ns=17).state is RunState.COMPLETED


def test_committed_effect_cannot_be_replaced():
    run = _run().record_effect(
        RunEffect(
            "effect-1", "idempotency-1", RunEffectStatus.COMMITTED, "receipt://effect-1"
        ),
        now_ns=11,
    )
    assert run.record_effect(run.effects[0], now_ns=12) is run
    with pytest.raises(DuplicateCommittedEffect):
        run.record_effect(
            RunEffect("effect-1", "different", RunEffectStatus.COMMITTED), now_ns=12
        )


def test_serialization_and_hash_are_stable():
    run = _run().add_receipt("receipt://run-1/goal", now_ns=11)
    restored = PersistentRun.from_json(run.to_json())
    assert restored == run
    assert restored.content_hash() == run.content_hash()
    assert restored.to_dict()["schema_version"] == "simplicio.persistent-run/v1"


def test_sensitive_provider_state_and_duplicates_fail_closed():
    with pytest.raises(PersistentRunError, match="sensitive"):
        PersistentRun.create(
            run_id="run-1", goal_hash="goal", provider_state={"api_token": "x"}
        )
    with pytest.raises(PersistentRunError, match="duplicate"):
        PersistentRun(
            run_id="run-1",
            goal_hash="goal",
            budgets=(("tokens", 1), ("tokens", 2)),
            created_at_ns=1,
            updated_at_ns=1,
        )
