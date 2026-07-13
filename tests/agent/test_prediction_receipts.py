from __future__ import annotations

import json

import pytest

from agent.prediction_receipts import (
    Counterfactual,
    CounterfactualKind,
    Observation,
    ObservationState,
    PredictionOutcome,
    PredictionReceipt,
    ReconciliationDecision,
)


def _receipt(**changes) -> PredictionReceipt:
    values = {
        "action_digest": "sha256:effect-1",
        "preconditions": ("receipt:previous", "belief:balance@v2"),
        "expected_effects": (Observation.known("balance", 10),),
        "allowed_variance": {"balance": 0.5},
        "confidence": 0.8,
        "risk": "medium",
        "cost_estimate": 3,
        "verifier": "ledger.balance",
        "rollback": "compensate:refund",
        "counterfactuals": (
            Counterfactual(
                CounterfactualKind.NO_ACTION,
                "leave unchanged",
                Observation.known("balance", 8),
                "ledger-v1",
            ),
            Counterfactual(
                CounterfactualKind.ALTERNATIVE,
                "defer",
                Observation.known("balance", 9),
                "ledger-v1",
            ),
        ),
    }
    values.update(changes)
    return PredictionReceipt(**values)


def test_serialization_is_canonical_and_round_trips() -> None:
    receipt = _receipt()

    encoded = receipt.to_json()

    assert encoded == receipt.to_json()
    assert encoded == json.dumps(
        receipt.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert PredictionReceipt.from_json(encoded) == receipt


def test_expected_effects_and_counterfactuals_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="verifiable"):
        _receipt(expected_effects=(Observation.known("status", "must work"),))
    with pytest.raises(ValueError, match="unknown or error"):
        _receipt(expected_effects=(Observation.unknown("status", "not checked"),))
    with pytest.raises(ValueError, match="model-only"):
        Counterfactual(
            CounterfactualKind.ALTERNATIVE,
            "unsafe",
            Observation.known("status", "ok"),
            "model-v1",
            execution="executed",
        )


def test_match_uses_allowed_variance_without_learning_error() -> None:
    assessed = _receipt().assess((Observation.known("balance", 10.4),))

    assert assessed.outcome is PredictionOutcome.MATCH
    assert assessed.prediction_error.state is ObservationState.KNOWN
    assert assessed.prediction_error.rate == 0
    assert assessed.reconciliation is ReconciliationDecision.NONE
    assert assessed.update_decision == "no_update"


def test_partial_mismatch_requests_belief_and_strategy_update() -> None:
    receipt = _receipt(
        expected_effects=(
            Observation.known("balance", 10),
            Observation.known("status", "settled"),
        ),
    )

    assessed = receipt.assess((
        Observation.known("balance", 10),
        Observation.known("status", "pending"),
    ))

    assert assessed.outcome is PredictionOutcome.PARTIAL_MATCH
    assert assessed.prediction_error.rate == 0.5
    assert assessed.reconciliation is ReconciliationDecision.UPDATE_BELIEF
    assert assessed.update_decision == "update_belief_and_strategy"


def test_unknown_and_error_never_become_mismatches() -> None:
    unknown = _receipt().assess((Observation.unknown("balance", "timeout"),))
    error = _receipt().assess((Observation.error("balance", "verifier crashed"),))
    missing = _receipt().assess(())

    assert unknown.outcome is PredictionOutcome.UNKNOWN
    assert unknown.prediction_error.state is ObservationState.UNKNOWN
    assert unknown.reconciliation is ReconciliationDecision.RECONCILE
    assert missing.outcome is PredictionOutcome.UNKNOWN
    with pytest.raises(ValueError, match="already been assessed"):
        missing.assess(())
    assert error.outcome is PredictionOutcome.ERROR
    assert error.prediction_error.state is ObservationState.ERROR
    assert error.reconciliation is ReconciliationDecision.ESCALATE


def test_receipt_links_to_existing_content_addressed_ledger(tmp_path) -> None:
    ledger_receipt = _receipt().record_ledger(tmp_path)

    assert ledger_receipt.yool_id == "agent.consciousness.prediction"
    assert (tmp_path / f"{ledger_receipt.sha}.json").is_file()
