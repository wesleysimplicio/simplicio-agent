from __future__ import annotations

from agent.event_store import AwarenessReceipt, OperationalValueStatus
from agent.belief_state import Freshness, SourceReliability
from agent.operational_cycle import OperationalAwarenessCycle
from agent.operational_now import Degradation, OperationalNowStore
from agent.prediction_receipts import (
    Counterfactual,
    CounterfactualKind,
    Observation,
    Precondition,
    PreconditionKind,
    PredictionOutcome,
    PredictionReceipt,
    TimeoutReconciliation,
    Verifier,
)


def _prediction(**changes: object) -> PredictionReceipt:
    values = {
        "action_digest": "sha256:cycle-action",
        "preconditions": (Precondition(PreconditionKind.BELIEF, "belief.balance"),),
        "expected_effects": (Observation.known("balance", 10),),
        "confidence": 0.8,
        "risk": "low",
        "cost_estimate": 1,
        "verifier": Verifier("balance", "ledger.balance"),
        "rollback": "refund",
        "counterfactuals": (
            Counterfactual(CounterfactualKind.NO_ACTION, "none", Observation.known("balance", 8), "ledger"),
            Counterfactual(CounterfactualKind.ALTERNATIVE, "defer", Observation.known("balance", 9), "ledger"),
        ),
        "timeout_reconciliation": TimeoutReconciliation("effects", "ledger.balance"),
        "strategy_fingerprint": "strategy:cycle",
    }
    values.update(changes)
    return PredictionReceipt(**values)


def _belief(*, freshness: Freshness = Freshness.FRESH) -> AwarenessReceipt:
    return AwarenessReceipt(
        receipt_id="belief-receipt",
        path="belief.balance",
        value=8,
        status=OperationalValueStatus.MEASURED,
        freshness=freshness,
        source="ledger",
        source_event_id="balance-event",
        recorded_at_ns=1,
        confidence=0.9,
        payload={"run_id": "run-1", "profile_id": "profile-1"},
    )


def test_cycle_authorizes_only_when_belief_precondition_is_fresh(tmp_path):
    cycle = OperationalAwarenessCycle(
        OperationalNowStore(
            event_log_path=tmp_path / "events.jsonl",
            snapshot_path=tmp_path / "snapshot.json",
            source_reliability={"ledger": SourceReliability("ledger", "1", 1.0)},
        )
    )
    cycle.observe([_belief()])

    decision = cycle.authorize(_prediction())

    assert decision.allowed is True
    assert decision.reason == "fresh prediction preconditions verified"


def test_cycle_blocks_stale_or_missing_preconditions(tmp_path):
    cycle = OperationalAwarenessCycle(
        OperationalNowStore(
            event_log_path=tmp_path / "events.jsonl",
            snapshot_path=tmp_path / "snapshot.json",
            source_reliability={"ledger": SourceReliability("ledger", "1", 1.0)},
        )
    )
    cycle.observe([_belief(freshness=Freshness.STALE)])

    decision = cycle.authorize(_prediction())

    assert decision.allowed is False
    assert decision.missing_preconditions == ("belief.balance",)
    assert cycle.snapshot().beliefs["belief.balance"].freshness is Freshness.STALE


def test_reconcile_persists_prediction_result_and_replays(tmp_path):
    store = OperationalNowStore(
        event_log_path=tmp_path / "events.jsonl", snapshot_path=tmp_path / "snapshot.json"
    )
    cycle = OperationalAwarenessCycle(store, clock_ns=lambda: 2)
    result = cycle.reconcile(_prediction(), [Observation.known("balance", 10)])

    assert result.prediction.outcome is PredictionOutcome.MATCH
    assert result.awareness_receipt.status is OperationalValueStatus.MEASURED
    assert result.snapshot.get("prediction.sha256:cycle-action") is not None
    assert cycle.snapshot().snapshot_hash == result.snapshot.snapshot_hash
