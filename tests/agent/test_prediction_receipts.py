from __future__ import annotations

import json

import pytest

from agent.prediction_receipts import (
    ConfidenceCalibration,
    Counterfactual,
    CounterfactualKind,
    counterfactual_evidence_digest,
    HardPolicyConstraint,
    Observation,
    ObservationState,
    Precondition,
    PreconditionKind,
    PredictionError,
    PredictionOutcome,
    PredictionReceipt,
    prediction_evidence_digest,
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

    with pytest.raises(ValueError, match="kind and label must be unique"):
        _receipt(
            counterfactuals=(
                Counterfactual(
                    CounterfactualKind.NO_ACTION,
                    "same",
                    Observation.known("balance", 8),
                    "ledger-v1",
                ),
                Counterfactual(
                    CounterfactualKind.NO_ACTION,
                    "same",
                    Observation.known("balance", 7),
                    "ledger-v1",
                ),
                Counterfactual(
                    CounterfactualKind.ALTERNATIVE,
                    "defer",
                    Observation.known("balance", 9),
                    "ledger-v1",
                ),
            )
        )


def test_counterfactual_digest_is_canonical_and_model_only() -> None:
    receipt = _receipt()
    reordered = _receipt(counterfactuals=tuple(reversed(receipt.counterfactuals)))

    assert counterfactual_evidence_digest(receipt) == counterfactual_evidence_digest(
        reordered
    )
    changed = _receipt(
        counterfactuals=(
            next(
                item
                for item in receipt.counterfactuals
                if item.kind is CounterfactualKind.NO_ACTION
            ),
            Counterfactual(
                CounterfactualKind.ALTERNATIVE,
                "defer",
                Observation.known("balance", 99),
                "ledger-v1",
            ),
        )
    )
    assert counterfactual_evidence_digest(changed) != counterfactual_evidence_digest(
        receipt
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


def test_error_outcome_ledger_status_is_error(tmp_path) -> None:
    error_receipt = _receipt().assess(
        (Observation.error("balance", "verifier crashed"),)
    )

    ledger_receipt = error_receipt.record_ledger(tmp_path)

    assert ledger_receipt.status == "error"


def test_precondition_from_value_rejects_bad_strings() -> None:
    with pytest.raises(ValueError, match="belief:<ref> or receipt:<sha>"):
        Precondition.from_value("nope")
    with pytest.raises(ValueError, match="belief:<ref> or receipt:<sha>"):
        Precondition.from_value("weird:ref")

    from_string = Precondition.from_value("belief:balance@v1")
    assert from_string.kind is PreconditionKind.BELIEF
    assert from_string.reference == "balance@v1"

    from_dict = Precondition.from_value(
        {"kind": "receipt", "reference": "sha256:abc", "fresh": True}
    )
    assert from_dict.kind is PreconditionKind.RECEIPT

    with pytest.raises(ValueError, match="non-empty"):
        Precondition(PreconditionKind.BELIEF, "  ")


def test_verifier_from_value_variants_and_validation() -> None:
    with pytest.raises(ValueError, match="declared"):
        Verifier.from_value("   ")

    from_string = Verifier.from_value("ledger.balance")
    assert from_string.label == "ledger.balance"
    assert from_string.source == "ledger.balance"

    from_dict = Verifier.from_value({"label": "a", "source": "b"})
    assert from_dict.label == "a"
    assert from_dict.source == "b"

    with pytest.raises(ValueError, match="must be declared"):
        Verifier("", "source")


def test_timeout_reconciliation_requires_fields_and_rejects_retry() -> None:
    with pytest.raises(ValueError, match="effect journal and verifier query"):
        TimeoutReconciliation(effect_journal_ref="", verifier_query="q")
    with pytest.raises(ValueError, match="cannot permit blind retry"):
        TimeoutReconciliation(
            effect_journal_ref="ref", verifier_query="q", retry_permitted=True
        )


def test_hard_policy_constraint_validation() -> None:
    with pytest.raises(ValueError, match="label must be non-empty"):
        HardPolicyConstraint("  ", "high", 1)
    with pytest.raises(ValueError, match="low/medium/high/critical"):
        HardPolicyConstraint("label", "extreme", 1)
    with pytest.raises(ValueError, match="non-negative"):
        HardPolicyConstraint("label", "high", -1)


def test_prediction_error_validation() -> None:
    with pytest.raises(ValueError, match="rate between 0 and 1"):
        PredictionError(ObservationState.KNOWN, rate=None)
    with pytest.raises(ValueError, match="rate between 0 and 1"):
        PredictionError(ObservationState.KNOWN, rate=1.5)
    with pytest.raises(ValueError, match="cannot carry a reason"):
        PredictionError(ObservationState.KNOWN, rate=0.5, reason="oops")
    with pytest.raises(ValueError, match="requires a reason only"):
        PredictionError(ObservationState.UNKNOWN)
    with pytest.raises(ValueError, match="requires a reason only"):
        PredictionError(ObservationState.UNKNOWN, rate=0.1, reason="set")


def test_confidence_calibration_validation() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ConfidenceCalibration(ObservationState.KNOWN, predicted_confidence=1.5)
    with pytest.raises(ValueError, match="requires observed accuracy"):
        ConfidenceCalibration(ObservationState.KNOWN, predicted_confidence=0.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        ConfidenceCalibration(
            ObservationState.KNOWN, predicted_confidence=0.5, observed_accuracy=2.0
        )
    with pytest.raises(ValueError, match="cannot carry a reason"):
        ConfidenceCalibration(
            ObservationState.KNOWN,
            predicted_confidence=0.5,
            observed_accuracy=0.5,
            reason="nope",
        )
    with pytest.raises(ValueError, match="requires a reason"):
        ConfidenceCalibration(ObservationState.UNKNOWN, predicted_confidence=0.5)


def test_observation_validation() -> None:
    with pytest.raises(ValueError, match="key must be non-empty"):
        Observation(key="  ", value=1)
    with pytest.raises(ValueError, match="requires a value"):
        Observation(key="k")
    with pytest.raises(ValueError, match="cannot carry a reason"):
        Observation(key="k", value=1, reason="nope")
    with pytest.raises(ValueError, match="requires a reason only"):
        Observation(key="k", state=ObservationState.UNKNOWN)

    with pytest.raises(ValueError, match="serialized value"):
        Observation.from_dict({"key": "k", "state": "known"})

    round_tripped = Observation.from_dict(
        Observation.unknown("k", "timeout").to_dict()
    )
    assert round_tripped.state is ObservationState.UNKNOWN
    assert round_tripped.reason == "timeout"


def test_observation_keys_must_be_unique() -> None:
    with pytest.raises(ValueError, match="unique"):
        _receipt(
            expected_effects=(
                Observation.known("balance", 10),
                Observation.known("balance", 11),
            )
        )


def test_precondition_references_must_be_unique() -> None:
    with pytest.raises(ValueError, match="precondition references must be unique"):
        _receipt(
            preconditions=(
                Precondition(PreconditionKind.RECEIPT, "same"),
                Precondition(PreconditionKind.RECEIPT, "same"),
            )
        )


def test_policy_constraint_labels_must_be_unique() -> None:
    with pytest.raises(ValueError, match="labels must be unique"):
        _receipt(
            hard_policy_constraints=(
                HardPolicyConstraint("dup", "high", 5),
                HardPolicyConstraint("dup", "high", 5),
            )
        )


def test_risk_rank_rejects_unknown_risk() -> None:
    with pytest.raises(ValueError, match="risk must be low/medium/high/critical"):
        _receipt(risk="unbounded")


def test_counterfactual_required_rejects_missing_alternative_kind() -> None:
    with pytest.raises(ValueError, match="no_action and alternative"):
        _receipt(
            counterfactuals=(
                Counterfactual(
                    CounterfactualKind.NO_ACTION,
                    "only",
                    Observation.known("balance", 8),
                    "ledger-v1",
                ),
            )
        )


def test_counterfactual_not_required_allows_empty() -> None:
    receipt = _receipt(counterfactuals=(), counterfactual_required=False)
    assert receipt.counterfactuals == ()


def test_receipt_requires_action_digest_and_preconditions_and_expected_effects() -> None:
    with pytest.raises(ValueError, match="action_digest must be non-empty"):
        _receipt(action_digest="  ")
    with pytest.raises(ValueError, match="preconditions must reference"):
        _receipt(preconditions=())
    with pytest.raises(ValueError, match="allowed_variance may only name"):
        _receipt(allowed_variance={"unknown_key": 1.0})
    with pytest.raises(ValueError, match="finite and non-negative"):
        _receipt(allowed_variance={"balance": -1.0})
    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        _receipt(confidence=1.2)
    with pytest.raises(ValueError, match="risk, verifier, and rollback"):
        _receipt(risk="", rollback="compensate")
    with pytest.raises(ValueError, match="risk, verifier, and rollback"):
        _receipt(rollback="  ")
    with pytest.raises(ValueError, match="cost_estimate must be non-negative"):
        _receipt(cost_estimate=-1)
    with pytest.raises(ValueError, match="timeout_reconciliation must be declared"):
        _receipt(timeout_reconciliation=None)
    with pytest.raises(ValueError, match="strategy_fingerprint must be declared"):
        _receipt(strategy_fingerprint="  ")


def test_pending_receipt_cannot_carry_assessment_data() -> None:
    with pytest.raises(ValueError, match="cannot contain assessment data"):
        _receipt(outcome=PredictionOutcome.PENDING, failure_fingerprint="oops")


def test_assessed_receipt_requires_reconciliation_data() -> None:
    with pytest.raises(ValueError, match="requires reconciliation data"):
        _receipt(
            outcome=PredictionOutcome.MATCH,
            reconciliation=ReconciliationDecision.NONE,
            update_decision="pending",
        )


def test_match_outcome_cannot_carry_failure_fingerprint_or_change_strategy() -> None:
    with pytest.raises(ValueError, match="cannot carry a failure fingerprint"):
        _receipt(
            outcome=PredictionOutcome.MATCH,
            reconciliation=ReconciliationDecision.NONE,
            update_decision="no_update",
            failure_fingerprint="oops",
        )
    with pytest.raises(ValueError, match="cannot change strategy fingerprint"):
        _receipt(
            outcome=PredictionOutcome.MATCH,
            reconciliation=ReconciliationDecision.NONE,
            update_decision="no_update",
            next_strategy_fingerprint="strategy:different",
        )


def test_non_match_outcome_requires_failure_fingerprint_and_new_strategy() -> None:
    with pytest.raises(ValueError, match="require a failure fingerprint"):
        _receipt(
            outcome=PredictionOutcome.MISMATCH,
            reconciliation=ReconciliationDecision.UPDATE_BELIEF,
            update_decision="update_belief_and_strategy",
        )
    with pytest.raises(ValueError, match="must change strategy fingerprint"):
        _receipt(
            outcome=PredictionOutcome.MISMATCH,
            reconciliation=ReconciliationDecision.UPDATE_BELIEF,
            update_decision="update_belief_and_strategy",
            failure_fingerprint="mismatch:balance",
            next_strategy_fingerprint="strategy:baseline",
        )


def test_from_dict_rejects_unsupported_schema() -> None:
    payload = _receipt().to_dict()
    payload["schema"] = "bogus"
    with pytest.raises(ValueError, match="unsupported prediction receipt schema"):
        PredictionReceipt.from_dict(payload)

    payload = _receipt().to_dict()
    payload["schema_version"] = "bogus"
    with pytest.raises(ValueError, match="unsupported prediction receipt schema version"):
        PredictionReceipt.from_dict(payload)


def test_unresolved_and_extra_observations_are_tracked_correctly() -> None:
    receipt = _receipt(
        expected_effects=(
            Observation.known("balance", 10),
            Observation.known("status", "settled"),
        ),
    )

    assessed = receipt.assess(
        (
            Observation.known("balance", 10),
            Observation.error("status", "verifier crashed"),
            Observation.unknown("extra_unresolved", "not checked"),
            Observation.error("extra_error", "verifier crashed"),
            Observation.known("extra_mismatch", "unexpected"),
        )
    )

    assert assessed.outcome is PredictionOutcome.ERROR
    assert "status" in assessed.prediction_error.reason
    assert "extra_error" in assessed.prediction_error.reason


def test_prediction_evidence_digest_requires_receipt_type() -> None:
    with pytest.raises(TypeError, match="requires a PredictionReceipt"):
        prediction_evidence_digest("not-a-receipt")


def test_counterfactual_evidence_digest_requires_receipt_type() -> None:
    with pytest.raises(TypeError, match="requires a PredictionReceipt"):
        counterfactual_evidence_digest("not-a-receipt")
