from __future__ import annotations

import json

import pytest

from agent.prediction_receipts import (
    ConfidenceCalibration,
    Counterfactual,
    CounterfactualKind,
    HardPolicyConstraint,
    Observation,
    ObservationState,
    Precondition,
    PreconditionKind,
    PredictionOutcome,
    PredictionReceipt,
    ReconciliationDecision,
    TimeoutReconciliation,
    Verifier,
)


def _receipt(**changes) -> PredictionReceipt:
    values = {
        "action_digest": "sha256:effect-1",
        "preconditions": (
            Precondition(PreconditionKind.RECEIPT, "previous"),
            Precondition(PreconditionKind.BELIEF, "balance@v2"),
        ),
        "expected_effects": (Observation.known("balance", 10),),
        "allowed_variance": {"balance": 0.5},
        "confidence": 0.8,
        "risk": "medium",
        "cost_estimate": 3,
        "verifier": Verifier("ledger.balance", "watcher:ledger.balance"),
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
        "timeout_reconciliation": TimeoutReconciliation(
            effect_journal_ref="effect-journal:balance",
            verifier_query="watcher.requery(balance)",
        ),
        "hard_policy_constraints": (
            HardPolicyConstraint("bounded_cost", "high", 5),
        ),
        "strategy_fingerprint": "strategy:baseline",
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
    with pytest.raises(ValueError, match="fresh"):
        _receipt(preconditions=(Precondition(PreconditionKind.BELIEF, "old", False),))
    with pytest.raises(ValueError, match="recomputable"):
        _receipt(verifier=Verifier("ledger.balance", "watcher", recomputable=False))
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
    assert assessed.failure_fingerprint == ""
    assert assessed.next_strategy_fingerprint == assessed.strategy_fingerprint


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
    assert assessed.failure_fingerprint == "partial:status"
    assert assessed.next_strategy_fingerprint != assessed.strategy_fingerprint


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
    assert error.next_strategy_fingerprint != error.strategy_fingerprint


def test_confidence_calibration_stays_explicitly_unknown_without_measurement() -> None:
    pending = _receipt().confidence_calibration()
    unresolved = _receipt().assess(()).confidence_calibration()

    for calibration in (pending, unresolved):
        assert isinstance(calibration, ConfidenceCalibration)
        assert calibration.state is ObservationState.UNKNOWN
        assert calibration.observed_accuracy is None
        assert calibration.absolute_residual is None
        assert calibration.reason
        assert calibration.to_dict()["state"] == ObservationState.UNKNOWN.value
        assert calibration.to_dict()["observed_accuracy"] is None
        assert calibration.to_dict()["absolute_residual"] is None


def test_confidence_calibration_uses_only_measured_prediction_error() -> None:
    matched = _receipt(confidence=0.8).assess((Observation.known("balance", 10),))
    mismatched = _receipt(confidence=0.8).assess((Observation.known("balance", 0),))
    verifier_error = _receipt(confidence=0.8).assess((
        Observation.error("balance", "verifier crashed"),
    ))

    match_calibration = matched.confidence_calibration()
    mismatch_calibration = mismatched.confidence_calibration()
    error_calibration = verifier_error.confidence_calibration()

    assert match_calibration.state is ObservationState.KNOWN
    assert match_calibration.observed_accuracy == 1.0
    assert match_calibration.absolute_residual == pytest.approx(0.2)
    assert mismatch_calibration.state is ObservationState.KNOWN
    assert mismatch_calibration.observed_accuracy == 0.0
    assert mismatch_calibration.absolute_residual == pytest.approx(0.8)
    assert error_calibration.state is ObservationState.ERROR
    assert error_calibration.observed_accuracy is None
    assert error_calibration.absolute_residual is None


def test_ambiguous_timeout_requires_effect_journal_reconciliation() -> None:
    assessed = _receipt().assess((), ambiguous_timeout=True)

    assert assessed.outcome is PredictionOutcome.UNKNOWN
    assert assessed.prediction_error.state is ObservationState.UNKNOWN
    assert (
        assessed.reconciliation is ReconciliationDecision.CHECK_EFFECT_JOURNAL
    )
    assert assessed.update_decision == "consult_effect_journal_before_retry"
    assert assessed.failure_fingerprint == "ambiguous_timeout:balance"
    assert assessed.next_strategy_fingerprint != assessed.strategy_fingerprint


def test_hard_policy_constraints_reject_over_budget_or_over_risk() -> None:
    with pytest.raises(ValueError, match="risk exceeds"):
        _receipt(
            risk="critical",
            hard_policy_constraints=(HardPolicyConstraint("safe_risk", "high", 5),),
        )
    with pytest.raises(ValueError, match="cost exceeds"):
        _receipt(
            cost_estimate=7,
            hard_policy_constraints=(HardPolicyConstraint("safe_cost", "critical", 5),),
        )


def test_receipt_links_to_existing_content_addressed_ledger(tmp_path) -> None:
    ledger_receipt = _receipt().record_ledger(tmp_path)

    assert ledger_receipt.yool_id == "agent.consciousness.prediction"
    assert (tmp_path / f"{ledger_receipt.sha}.json").is_file()
