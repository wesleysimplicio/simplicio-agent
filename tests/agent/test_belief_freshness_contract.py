"""Focused contract tests for belief freshness, conflict, and uncertainty."""

from __future__ import annotations

import pytest

from agent.belief_state import (
    BeliefDecision,
    BeliefObservation,
    BeliefStateEngine,
    Freshness,
    SourceReliability,
)


def _engine() -> BeliefStateEngine:
    return BeliefStateEngine(
        source_reliability={"sensor": SourceReliability("sensor", "v1", 1.0)}
    )


def test_fresh_observation_satisfies_required_freshness() -> None:
    assessment = _engine().fuse(
        (
            BeliefObservation(
                "deployment.status",
                "sensor",
                "evt-fresh",
                value="ready",
                freshness=Freshness.FRESH,
                confidence=0.9,
            ),
        ),
        require_fresh=True,
    )

    assert assessment.decision is BeliefDecision.ACCEPT
    assert assessment.reason == "accepted"
    assert assessment.required_observation is None
    assert assessment.uncertainty == pytest.approx(0.1)


def test_unknown_freshness_fails_required_freshness_explicitly() -> None:
    assessment = _engine().fuse(
        (
            BeliefObservation(
                "deployment.status",
                "sensor",
                "evt-unknown",
                value="ready",
                freshness=Freshness.UNKNOWN,
                confidence=0.9,
            ),
        ),
        require_fresh=True,
    )

    assert assessment.decision is BeliefDecision.BLOCK
    assert assessment.reason == "freshness unknown"
    assert assessment.required_observation == "deployment.status"
    assert assessment.uncertainty >= 0.8


def test_distribution_disagreement_is_conflict_with_elevated_uncertainty() -> None:
    assessment = _engine().fuse(
        (
            BeliefObservation(
                "deployment.status",
                "sensor",
                "evt-ready",
                distribution=(("ready", 0.9), ("blocked", 0.1)),
                freshness=Freshness.FRESH,
                confidence=0.9,
            ),
            BeliefObservation(
                "deployment.status",
                "sensor",
                "evt-blocked",
                distribution=(("ready", 0.2), ("blocked", 0.8)),
                freshness=Freshness.FRESH,
                confidence=0.8,
            ),
        )
    )

    assert assessment.decision is BeliefDecision.CLARIFY
    assert assessment.conflicts == ("deployment.status:evt-blocked",)
    assert assessment.evidence_to_change == ("evt-blocked",)
    assert assessment.uncertainty >= 0.65
    assert assessment.selected_fact is not None
    assert assessment.selected_fact.uncertainty == assessment.uncertainty
