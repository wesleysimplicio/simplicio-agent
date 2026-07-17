"""Coverage-filling unit tests for agent.belief_state.

These target validation branches, type coercion paths, and canonical-value
branches that the existing contract/decision-path tests do not exercise:
empty-string rejection, out-of-range confidence, default-confidence per
BeliefType, string-to-enum coercion on BeliefFact/BeliefAssessment, missing
observation validation, and time-field validation.
"""

from __future__ import annotations

import pytest

from agent.belief_state import (
    BeliefAssessment,
    BeliefDecision,
    BeliefFact,
    BeliefObservation,
    BeliefType,
    Freshness,
    SourceReliability,
    _default_confidence,
)


def test_text_field_rejects_blank_string() -> None:
    with pytest.raises(ValueError, match="source must be non-empty"):
        SourceReliability(source="   ", version="v1")


def test_unit_interval_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="reliability must be finite"):
        SourceReliability(source="s", version="v1", reliability=1.5)


def test_unit_interval_rejects_nan() -> None:
    with pytest.raises(ValueError, match="reliability must be finite"):
        SourceReliability(source="s", version="v1", reliability=float("nan"))


def test_default_confidence_per_belief_type() -> None:
    assert _default_confidence(BeliefType.OBSERVED) == 0.9
    assert _default_confidence(BeliefType.REMEMBERED) == 0.8
    assert _default_confidence(BeliefType.INFERRED) == 0.7
    assert _default_confidence(BeliefType.PREDICTED) == 0.6


def test_belief_observation_coerces_string_enums() -> None:
    obs = BeliefObservation(
        subject="s",
        source="sensor",
        source_event_id="e1",
        value="x",
        belief_type="inferred",
        freshness="stale",
    )
    assert obs.belief_type is BeliefType.INFERRED
    assert obs.freshness is Freshness.STALE


def test_missing_observation_cannot_carry_value() -> None:
    with pytest.raises(ValueError, match="missing observations cannot carry a value"):
        BeliefObservation(
            subject="s", source="sensor", source_event_id="e1", value="x", missing=True
        )


def test_missing_observation_cannot_carry_distribution() -> None:
    with pytest.raises(
        ValueError, match="missing observations cannot carry a distribution"
    ):
        BeliefObservation(
            subject="s",
            source="sensor",
            source_event_id="e1",
            distribution=(("a", 0.5),),
            missing=True,
        )


def test_observation_without_value_distribution_or_missing_flag_raises() -> None:
    with pytest.raises(
        ValueError,
        match="observations must carry either a value, a distribution, or missing=True",
    ):
        BeliefObservation(subject="s", source="sensor", source_event_id="e1")


@pytest.mark.parametrize("field_name", ["valid_time_ns", "system_time_ns", "expiry_ns"])
def test_time_fields_must_be_positive_integers(field_name: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be a positive integer"):
        BeliefObservation(
            subject="s",
            source="sensor",
            source_event_id="e1",
            value="x",
            **{field_name: 0},
        )


@pytest.mark.parametrize("field_name", ["valid_time_ns", "system_time_ns", "expiry_ns"])
def test_time_fields_reject_non_integer(field_name: str) -> None:
    with pytest.raises(ValueError, match=f"{field_name} must be a positive integer"):
        BeliefObservation(
            subject="s",
            source="sensor",
            source_event_id="e1",
            value="x",
            **{field_name: True},
        )


def test_canonical_value_missing() -> None:
    obs = BeliefObservation(
        subject="s", source="sensor", source_event_id="e1", missing=True
    )
    assert obs.canonical_value() == "<missing>"


def test_canonical_value_distribution() -> None:
    obs = BeliefObservation(
        subject="s",
        source="sensor",
        source_event_id="e1",
        distribution=(("a", 0.5), ("b", 0.5)),
    )
    assert "distribution" in obs.canonical_value()


def test_canonical_value_scalar() -> None:
    obs = BeliefObservation(
        subject="s", source="sensor", source_event_id="e1", value="ready"
    )
    assert obs.canonical_value() == '"ready"'


def test_belief_fact_coerces_string_enums() -> None:
    fact = BeliefFact(
        subject="s",
        value="x",
        distribution=(),
        source="sensor",
        source_event_id="e1",
        source_version="v1",
        belief_type="observed",
        freshness="fresh",
        confidence=0.9,
        uncertainty=0.1,
        valid_time_ns=None,
        system_time_ns=None,
        expiry_ns=None,
        missing=False,
    )
    assert fact.belief_type is BeliefType.OBSERVED
    assert fact.freshness is Freshness.FRESH


def test_belief_assessment_coerces_string_decision() -> None:
    assessment = BeliefAssessment(
        subject="s",
        decision="accept",
        facts=(),
    )
    assert assessment.decision is BeliefDecision.ACCEPT


def test_belief_assessment_to_dict_round_trip_fields() -> None:
    fact = BeliefObservation(
        subject="s",
        source="sensor",
        source_event_id="e1",
        value="ready",
        freshness=Freshness.FRESH,
        confidence=0.9,
    ).to_fact(SourceReliability("sensor", "v1", 1.0))
    assessment = BeliefAssessment(
        subject="s",
        decision=BeliefDecision.ACCEPT,
        facts=(fact,),
        reason="accepted",
    )
    payload = assessment.to_dict()
    assert payload["decision"] == "accept"
    assert payload["facts"][0]["subject"] == "s"
    assert payload["required_observation"] is None


def test_belief_observation_round_trips_through_dict() -> None:
    obs = BeliefObservation(
        subject="s",
        source="sensor",
        source_event_id="e1",
        value="ready",
        freshness=Freshness.FRESH,
        confidence=0.9,
        valid_time_ns=10,
        system_time_ns=20,
        expiry_ns=30,
        evidence_handles=("h1",),
    )
    restored = BeliefObservation.from_dict(obs.to_dict())
    assert restored == obs
    assert obs.content_hash() == restored.content_hash()


def test_belief_fact_round_trips_through_dict() -> None:
    fact = BeliefObservation(
        subject="s",
        source="sensor",
        source_event_id="e1",
        value="ready",
        freshness=Freshness.FRESH,
        confidence=0.9,
    ).to_fact(SourceReliability("sensor", "v1", 1.0))
    restored = BeliefFact.from_dict(fact.to_dict())
    assert restored == fact
    assert fact.content_hash() == restored.content_hash()


def test_reliability_for_unknown_source_defaults_to_half() -> None:
    from agent.belief_state import BeliefStateEngine

    engine = BeliefStateEngine()
    profile = engine.reliability_for("unknown-sensor")
    assert profile.reliability == 0.5
    assert profile.version == "default"


def test_engine_rejects_block_threshold_not_below_clarify() -> None:
    from agent.belief_state import BeliefStateEngine

    with pytest.raises(
        ValueError, match="block_threshold must be lower than clarify_threshold"
    ):
        BeliefStateEngine(clarify_threshold=0.5, block_threshold=0.5)
