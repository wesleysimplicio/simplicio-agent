"""Focused contract tests for the pure closed-loop policy slice."""

from __future__ import annotations

from agent.closed_loop_controller import (
    ActionBudget,
    ActionCandidate,
    ActionCost,
    ClosedLoopController,
    ControllerPolicy,
    DecisionKind,
    Freshness,
    ReasonCode,
    RiskClass,
    StateEstimate,
)


def cost(*, tokens: int = 10, safety_risk: float = 0.1) -> ActionCost:
    return ActionCost(100, tokens, 1.0, safety_risk, 0.0)


def candidate(
    digest: str,
    *,
    tokens: int = 10,
    risk: RiskClass = RiskClass.READ,
    mutating: bool = False,
    irreversible: bool = False,
    requires_human_gate: bool = False,
) -> ActionCandidate:
    return ActionCandidate(
        action_digest=digest,
        predicted_effect=f"effect:{digest}",
        cost=cost(tokens=tokens),
        verifier=f"verify:{digest}",
        risk=risk,
        mutating=mutating,
        irreversible=irreversible,
        expected_failure=0.1,
        uncertainty=0.1,
        requires_human_gate=requires_human_gate,
    )


FRESH_STATE = StateEstimate(
    freshness=Freshness.FRESH,
    confidence=0.95,
    capability_available=True,
)


def test_nominal_choice_is_cost_ordered_and_replayable():
    controller = ClosedLoopController()
    expensive = candidate("b-expensive", tokens=50)
    cheap = candidate("a-cheap", tokens=5)

    first = controller.decide("read the page", FRESH_STATE, [expensive, cheap])
    replay = controller.decide("read the page", FRESH_STATE, [cheap, expensive])

    assert first == replay
    assert first.kind is DecisionKind.ACTION
    assert first.action_digest == "a-cheap"
    assert first.reason_code is ReasonCode.ACTION_SELECTED
    assert first.predicted_cost == cheap.cost
    assert first.risk is RiskClass.READ
    assert first.verifier == "verify:a-cheap"
    assert first.alternatives_considered == ("a-cheap", "b-expensive")


def test_stale_conflicting_or_committed_state_never_retries_an_action():
    controller = ClosedLoopController()
    action = candidate("write-once", mutating=True, risk=RiskClass.REVERSIBLE_WRITE)

    for state, reason in (
        (
            StateEstimate(
                freshness=Freshness.STALE, confidence=0.99, capability_available=True
            ),
            ReasonCode.STATE_NOT_FRESH,
        ),
        (
            StateEstimate(
                freshness=Freshness.FRESH,
                confidence=0.99,
                conflicts=("dom",),
                capability_available=True,
            ),
            ReasonCode.CONFLICTING_OBSERVATIONS,
        ),
        (
            StateEstimate(
                freshness=Freshness.FRESH,
                confidence=0.99,
                capability_available=True,
                effect_committed=True,
            ),
            ReasonCode.COMMITTED_EFFECT_REQUIRES_RECONCILIATION,
        ),
    ):
        decision = controller.decide("write once", state, [action])
        assert decision.kind is DecisionKind.OBSERVE
        assert decision.reason_code is reason
        assert decision.action_digest == ""


def test_missing_confidence_fails_closed_before_mutation():
    state = StateEstimate(freshness=Freshness.FRESH, capability_available=True)
    action = candidate("mutate", mutating=True, risk=RiskClass.REVERSIBLE_WRITE)

    decision = ClosedLoopController().decide("change file", state, [action])

    assert decision.kind is DecisionKind.OBSERVE
    assert decision.reason_code is ReasonCode.LOW_PRECONDITION_CONFIDENCE


def test_high_risk_action_returns_clarify_with_prediction_receipt():
    action = candidate(
        "publish-1",
        risk=RiskClass.PUBLISH,
        mutating=True,
    )

    decision = ClosedLoopController().decide("publish release", FRESH_STATE, [action])

    assert decision.kind is DecisionKind.CLARIFY
    assert decision.reason_code is ReasonCode.HUMAN_GATE_REQUIRED
    assert decision.requires_human_gate is True
    assert decision.action_digest == "publish-1"
    assert decision.predicted_effect == "effect:publish-1"
    assert decision.risk is RiskClass.PUBLISH


def test_budget_and_capability_gates_are_explicit():
    over_budget = candidate("too-large", tokens=20)
    budgeted = ClosedLoopController(ControllerPolicy(budget=ActionBudget(tokens=10)))
    blocked = budgeted.decide("inspect", FRESH_STATE, [over_budget])
    assert blocked.kind is DecisionKind.BLOCK
    assert blocked.reason_code is ReasonCode.BUDGET_EXCEEDED

    unavailable = StateEstimate(freshness=Freshness.FRESH, confidence=0.95)
    waiting = ClosedLoopController().decide("inspect", unavailable, [candidate("read")])
    assert waiting.kind is DecisionKind.WAIT
    assert waiting.reason_code is ReasonCode.CAPABILITY_UNAVAILABLE


def test_decision_serialization_has_no_private_reasoning():
    decision = ClosedLoopController().decide(
        "inspect", FRESH_STATE, [candidate("read")]
    )

    payload = decision.to_dict()
    assert payload["schema_version"] == "simplicio.closed-loop-controller/v1"
    assert "reasoning" not in payload
    assert payload["predicted_cost"] == decision.predicted_cost.to_dict()
