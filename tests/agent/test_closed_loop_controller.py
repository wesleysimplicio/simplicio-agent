"""Focused contract tests for the bounded closed-loop controller slice."""

from __future__ import annotations

from agent.closed_loop_controller import (
    ActionBudget,
    ActionCandidate,
    ActionCost,
    ActionDecision,
    AntiOscillationState,
    BlockDecision,
    ClarifyDecision,
    ClosedLoopController,
    ConstraintStatus,
    ControllerPolicy,
    DecisionKind,
    Freshness,
    ObserveDecision,
    ReasonCode,
    RiskClass,
    StateEstimate,
    WaitDecision,
)


def cost(
    *,
    latency_ms: int = 100,
    tokens: int = 10,
    resource_units: float = 1.0,
    safety_risk: float = 0.1,
    irreversibility: float = 0.0,
) -> ActionCost:
    return ActionCost(
        latency_ms,
        tokens,
        resource_units,
        safety_risk,
        irreversibility,
    )


def candidate(
    digest: str,
    *,
    tokens: int = 10,
    uncertainty: float = 0.1,
    risk: RiskClass = RiskClass.READ,
    mutating: bool = False,
    irreversible: bool = False,
    irreversibility: float | None = None,
    requires_human_gate: bool = False,
) -> ActionCandidate:
    cost_irreversibility = irreversibility
    if cost_irreversibility is None:
        cost_irreversibility = 1.0 if irreversible else 0.0
    return ActionCandidate(
        action_digest=digest,
        predicted_effect=f"effect:{digest}",
        cost=cost(tokens=tokens, irreversibility=cost_irreversibility),
        verifier=f"verify:{digest}",
        risk=risk,
        mutating=mutating,
        irreversible=irreversible,
        expected_failure=0.1,
        uncertainty=uncertainty,
        requires_human_gate=requires_human_gate,
    )


FRESH_STATE = StateEstimate(
    freshness=Freshness.FRESH,
    confidence=0.95,
    capability_available=True,
)


def test_nominal_choice_is_typed_cost_ordered_and_replayable():
    controller = ClosedLoopController()
    expensive = candidate("b-expensive", tokens=50)
    cheap = candidate("a-cheap", tokens=5)

    first = controller.decide("read the page", FRESH_STATE, [expensive, cheap])
    replay = controller.decide("read the page", FRESH_STATE, [cheap, expensive])

    assert first == replay
    assert isinstance(first, ActionDecision)
    assert first.kind is DecisionKind.ACTION
    assert first.action_digest == "a-cheap"
    assert first.reason_code is ReasonCode.ACTION_SELECTED
    assert first.predicted_cost == cheap.cost
    assert first.risk is RiskClass.READ
    assert first.verifier == "verify:a-cheap"
    assert first.alternatives_considered == ("a-cheap", "b-expensive")
    assert any(
        receipt.constraint_id == "candidate.eligible"
        and receipt.status is ConstraintStatus.PASSED
        for receipt in first.constraint_receipts
    )


def test_uncertainty_above_policy_threshold_observes_instead_of_acting():
    controller = ClosedLoopController(
        ControllerPolicy(max_action_uncertainty=0.25)
    )

    decision = controller.decide(
        "inspect uncertain state",
        FRESH_STATE,
        [candidate("uncertain-read", uncertainty=0.26)],
    )

    assert isinstance(decision, ObserveDecision)
    assert decision.reason_code is ReasonCode.ACTION_UNCERTAINTY_TOO_HIGH
    assert decision.observation_request == "reduce_action_uncertainty"
    assert "policy.max_action_uncertainty<=0.25" in decision.active_constraints
    assert any(
        receipt.constraint_id == "candidate.uncertainty"
        and receipt.status is ConstraintStatus.WAITING
        and receipt.candidate_digest == "uncertain-read"
        for receipt in decision.constraint_receipts
    )


def test_uncertainty_threshold_is_inclusive_and_candidate_local():
    controller = ClosedLoopController(
        ControllerPolicy(max_action_uncertainty=0.25)
    )

    decision = controller.decide(
        "choose a bounded inspection",
        FRESH_STATE,
        [
            candidate("a-cheap-uncertain", tokens=1, uncertainty=0.26),
            candidate("b-threshold", tokens=20, uncertainty=0.25),
        ],
    )

    assert isinstance(decision, ActionDecision)
    assert decision.action_digest == "b-threshold"
    assert any(
        receipt.constraint_id == "candidate.uncertainty"
        and receipt.candidate_digest == "a-cheap-uncertain"
        for receipt in decision.constraint_receipts
    )


def test_missing_state_is_explicit_and_forces_observation():
    state = StateEstimate(
        freshness=Freshness.FRESH,
        confidence=0.99,
        capability_available=True,
        missing_inputs=("dom.anchor", "window.focus"),
    )

    decision = ClosedLoopController().decide("click confirm", state, [candidate("go")])

    assert isinstance(decision, ObserveDecision)
    assert decision.reason_code is ReasonCode.MISSING_OBSERVATIONS
    assert decision.missing_inputs == ("dom.anchor", "window.focus")
    assert decision.observation_request == "collect_missing_inputs"


def test_conflicting_or_committed_state_never_retries_an_action():
    controller = ClosedLoopController()
    action = candidate("write-once", mutating=True, risk=RiskClass.REVERSIBLE_WRITE)

    conflict = controller.decide(
        "write once",
        StateEstimate(
            freshness=Freshness.FRESH,
            confidence=0.99,
            conflicts=("dom:text!=vision:text",),
            capability_available=True,
        ),
        [action],
    )
    assert isinstance(conflict, ObserveDecision)
    assert conflict.reason_code is ReasonCode.CONFLICTING_OBSERVATIONS
    assert conflict.conflicting_inputs == ("dom:text!=vision:text",)

    committed = controller.decide(
        "write once",
        StateEstimate(
            freshness=Freshness.FRESH,
            confidence=0.99,
            capability_available=True,
            effect_committed=True,
        ),
        [action],
    )
    assert isinstance(committed, ObserveDecision)
    assert committed.reason_code is ReasonCode.COMMITTED_EFFECT_REQUIRES_RECONCILIATION
    assert committed.observation_request == "reconcile_committed_effect"


def test_low_confidence_stale_and_capability_waits_fail_closed():
    stale = ClosedLoopController().decide(
        "change file",
        StateEstimate(
            freshness=Freshness.STALE,
            confidence=0.95,
            capability_available=True,
        ),
        [candidate("mutate", mutating=True, risk=RiskClass.REVERSIBLE_WRITE)],
    )
    assert isinstance(stale, ObserveDecision)
    assert stale.reason_code is ReasonCode.STATE_NOT_FRESH

    low_confidence = ClosedLoopController().decide(
        "change file",
        StateEstimate(freshness=Freshness.FRESH, capability_available=True),
        [candidate("mutate", mutating=True, risk=RiskClass.REVERSIBLE_WRITE)],
    )
    assert isinstance(low_confidence, ObserveDecision)
    assert low_confidence.reason_code is ReasonCode.LOW_PRECONDITION_CONFIDENCE

    unavailable = ClosedLoopController().decide(
        "inspect",
        StateEstimate(freshness=Freshness.FRESH, confidence=0.95),
        [candidate("read")],
    )
    assert isinstance(unavailable, WaitDecision)
    assert unavailable.reason_code is ReasonCode.CAPABILITY_UNAVAILABLE
    assert unavailable.wait_for == "capability_health"


def test_high_risk_action_returns_typed_clarify_with_prediction_receipt():
    action = candidate(
        "publish-1",
        risk=RiskClass.PUBLISH,
        mutating=True,
    )

    decision = ClosedLoopController().decide("publish release", FRESH_STATE, [action])

    assert isinstance(decision, ClarifyDecision)
    assert decision.kind is DecisionKind.CLARIFY
    assert decision.reason_code is ReasonCode.HUMAN_GATE_REQUIRED
    assert decision.action_digest == "publish-1"
    assert decision.predicted_effect == "effect:publish-1"
    assert decision.risk is RiskClass.PUBLISH
    assert decision.clarify_prompt
    assert any(
        receipt.constraint_id == "human_gate"
        and receipt.status is ConstraintStatus.REQUIRES_CLARIFY
        for receipt in decision.constraint_receipts
    )


def test_positive_action_cost_irreversibility_monotonically_requires_human_gate():
    controller = ClosedLoopController()

    decisions = [
        controller.decide(
            "apply predicted effect",
            FRESH_STATE,
            [candidate("effect", irreversibility=irreversibility)],
        )
        for irreversibility in (0.0, 0.01, 0.5, 1.0)
    ]

    assert isinstance(decisions[0], ActionDecision)
    for decision in decisions[1:]:
        assert isinstance(decision, ClarifyDecision)
        assert decision.reason_code is ReasonCode.HUMAN_GATE_REQUIRED
        assert any(
            receipt.constraint_id == "human_gate"
            and receipt.status is ConstraintStatus.REQUIRES_CLARIFY
            for receipt in decision.constraint_receipts
        )


def test_budget_and_mutation_policy_constraints_are_explicit():
    over_budget = candidate("too-large", tokens=20)
    budgeted = ClosedLoopController(ControllerPolicy(budget=ActionBudget(tokens=10)))
    blocked = budgeted.decide("inspect", FRESH_STATE, [over_budget])
    assert isinstance(blocked, BlockDecision)
    assert blocked.reason_code is ReasonCode.BUDGET_EXCEEDED
    assert blocked.blocked_by == "budget"
    assert blocked.constraint_receipts[0].status is ConstraintStatus.BLOCKED

    mutation_disabled = ClosedLoopController(
        ControllerPolicy(allow_mutations=False)
    ).decide(
        "write file",
        FRESH_STATE,
        [candidate("mutate", mutating=True, risk=RiskClass.REVERSIBLE_WRITE)],
    )
    assert isinstance(mutation_disabled, BlockDecision)
    assert mutation_disabled.reason_code is ReasonCode.MUTATION_DISABLED
    assert mutation_disabled.blocked_by == "mutation_policy"


def test_anti_oscillation_waits_during_cooldown():
    decision = ClosedLoopController().decide(
        "retry flaky action",
        FRESH_STATE,
        [candidate("retry")],
        anti_oscillation=AntiOscillationState(
            fingerprint="fp-1",
            repeated_failures=2,
            cooldown_remaining=3,
            last_action_digest="retry",
        ),
    )

    assert isinstance(decision, WaitDecision)
    assert decision.reason_code is ReasonCode.OSCILLATION_COOLDOWN_ACTIVE
    assert decision.wait_for == "anti_oscillation_cooldown"
    assert decision.anti_oscillation is not None
    assert decision.anti_oscillation.suppressed_actions == ("retry",)


def test_anti_oscillation_prefers_alternative_safe_candidate():
    decision = ClosedLoopController().decide(
        "recover from repeated failure",
        FRESH_STATE,
        [candidate("retry"), candidate("fallback")],
        anti_oscillation=AntiOscillationState(
            fingerprint="fp-2",
            repeated_failures=2,
            last_action_digest="retry",
        ),
    )

    assert isinstance(decision, ActionDecision)
    assert decision.action_digest == "fallback"
    assert decision.anti_oscillation is not None
    assert decision.anti_oscillation.strategy_switch_required is True
    assert any(
        receipt.constraint_id == "anti_oscillation"
        and receipt.status is ConstraintStatus.SUPPRESSED
        and receipt.candidate_digest == "retry"
        for receipt in decision.constraint_receipts
    )


def test_anti_oscillation_blocks_when_no_safe_alternative_exists():
    decision = ClosedLoopController().decide(
        "recover from repeated failure",
        FRESH_STATE,
        [candidate("retry")],
        anti_oscillation=AntiOscillationState(
            fingerprint="fp-3",
            repeated_failures=2,
            last_action_digest="retry",
        ),
    )

    assert isinstance(decision, BlockDecision)
    assert decision.reason_code is ReasonCode.STRATEGY_SWITCH_REQUIRED
    assert decision.blocked_by == "anti_oscillation"


def test_decision_serialization_has_no_private_reasoning():
    decision = ClosedLoopController().decide(
        "inspect",
        FRESH_STATE,
        [candidate("read")],
    )

    payload = decision.to_dict()
    assert payload["schema_version"] == "simplicio.closed-loop-controller/v1"
    assert "reasoning" not in payload
    assert payload["kind"] == "action"
    assert payload["predicted_cost"] == decision.predicted_cost.to_dict()
