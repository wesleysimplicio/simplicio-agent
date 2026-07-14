"""Focused tests for deterministic hypothesis evidence pruning."""

from __future__ import annotations

import json

import pytest

from agent.hypothesis_ensemble import (
    HYPOTHESIS_PRUNING_POLICY_VERSION,
    HYPOTHESIS_PRUNING_SCHEMA_VERSION,
    HypothesisCandidate,
    prune_hypothesis_ensemble,
)


def candidate(hypothesis_id: str, **changes: object) -> HypothesisCandidate:
    values: dict[str, object] = {
        "hypothesis_id": hypothesis_id,
        "statement": f"candidate {hypothesis_id}",
        "confidence": 0.5,
        "temperature": 0.7,
    }
    values.update(changes)
    return HypothesisCandidate(**values)  # type: ignore[arg-type]


def test_explicit_evidence_pruning_is_order_independent_and_receipted() -> None:
    refuted = candidate(
        "refuted",
        confidence=0.95,
        temperature=0.1,
        supporting_evidence=("receipt:support",),
        refuting_evidence=("receipt:refute-b", "receipt:refute-a"),
    )
    uncertain = candidate(
        "uncertain",
        confidence=0.1,
        temperature=1.9,
    )

    receipt = prune_hypothesis_ensemble((refuted, uncertain))
    replay = prune_hypothesis_ensemble((uncertain, refuted))

    assert receipt == replay
    assert receipt.receipt_hash == replay.receipt_hash
    assert receipt.kept_ids == ("uncertain",)
    assert tuple(record.hypothesis_id for record in receipt.pruned) == ("refuted",)
    assert receipt.pruned[0].refuting_evidence == (
        "receipt:refute-a",
        "receipt:refute-b",
    )

    payload = receipt.to_dict()
    assert payload["schema_version"] == HYPOTHESIS_PRUNING_SCHEMA_VERSION
    assert payload["policy_version"] == HYPOTHESIS_PRUNING_POLICY_VERSION
    assert len(payload["input_hash"]) == 64
    assert len(payload["receipt_hash"]) == 64
    json.dumps(payload, sort_keys=True)


def test_temperature_and_confidence_are_not_pruning_evidence() -> None:
    low_confidence_hot_sample = candidate(
        "hot",
        confidence=0.0,
        temperature=2.0,
    )
    evidence_tie = candidate(
        "tie",
        supporting_evidence=("receipt:support",),
        refuting_evidence=("receipt:refute",),
    )

    receipt = prune_hypothesis_ensemble((evidence_tie, low_confidence_hot_sample))

    assert receipt.kept_ids == ("hot", "tie")
    assert receipt.pruned == ()


@pytest.mark.parametrize("temperature", [-0.1, 2.1, float("inf"), float("nan")])
def test_candidate_rejects_invalid_temperature(temperature: float) -> None:
    with pytest.raises(ValueError, match="temperature"):
        candidate("invalid", temperature=temperature)


def test_contract_rejects_ambiguous_or_unbounded_ensembles() -> None:
    with pytest.raises(ValueError, match="both support and refute"):
        candidate(
            "ambiguous",
            supporting_evidence=("receipt:same",),
            refuting_evidence=("receipt:same",),
        )

    duplicate = candidate("duplicate")
    with pytest.raises(ValueError, match="must be unique"):
        prune_hypothesis_ensemble((duplicate, duplicate))

    with pytest.raises(ValueError, match="exceeds max_candidates"):
        prune_hypothesis_ensemble(
            (candidate("one"), candidate("two"), candidate("three")),
            max_candidates=2,
        )
