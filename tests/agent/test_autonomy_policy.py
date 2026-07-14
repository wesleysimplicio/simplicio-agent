"""Focused autonomy policy tests for issue #156."""

from agent.autonomy_policy import (
    ActionRequest,
    ActionRisk,
    ApprovalGrant,
    AutonomyLevel,
    AutonomyPolicy,
    PolicyDecisionKind,
    PolicyReason,
)


def _action(risk=ActionRisk.READ, *, mutating=False):
    return ActionRequest(
        "sha256:action", "sha256:goal", "workspace:one", risk, mutating
    )


def test_levels_and_high_risk_defaults_are_explainable():
    policy = AutonomyPolicy(level=AutonomyLevel.L3_GOAL_SCOPED)
    assert policy.decide(_action(), now_ns=10).kind is PolicyDecisionKind.ALLOW
    decision = policy.decide(_action(ActionRisk.PAYMENT, mutating=True), now_ns=10)
    assert decision.kind is PolicyDecisionKind.ASK
    assert decision.reason is PolicyReason.HUMAN_GATE_REQUIRED
    assert policy.explain()["level"] == "L3"


def test_supervised_mode_asks_for_mutations_but_allows_read():
    policy = AutonomyPolicy(level=AutonomyLevel.L2_SUPERVISED)
    assert policy.decide(_action(), now_ns=10).kind is PolicyDecisionKind.ALLOW
    assert (
        policy.decide(
            _action(ActionRisk.REVERSIBLE_WRITE, mutating=True), now_ns=10
        ).kind
        is PolicyDecisionKind.ASK
    )


def test_approval_is_bound_to_digest_goal_scope_policy_and_expiry():
    policy = AutonomyPolicy(level=AutonomyLevel.L3_GOAL_SCOPED)
    approval = ApprovalGrant(
        "sha256:action", "sha256:goal", "workspace:one", 20, policy.policy_version
    )
    action = _action(ActionRisk.PAYMENT, mutating=True)
    assert (
        policy.decide(action, now_ns=19, approval=approval).kind
        is PolicyDecisionKind.ALLOW
    )
    assert (
        policy.decide(action, now_ns=21, approval=approval).reason
        is PolicyReason.HUMAN_GATE_REQUIRED
    )
    other = ActionRequest(
        "sha256:other", action.goal_hash, action.scope, action.risk, action.mutating
    )
    assert (
        policy.decide(other, now_ns=19, approval=approval).kind
        is PolicyDecisionKind.ASK
    )


def test_killswitch_denies_even_a_valid_approval():
    policy = AutonomyPolicy(level=AutonomyLevel.L4_PERSISTENT)
    approval = ApprovalGrant(
        "sha256:action", "sha256:goal", "workspace:one", 20, policy.policy_version
    )
    decision = policy.with_killswitch().decide(
        _action(ActionRisk.DELETE, mutating=True), now_ns=10, approval=approval
    )
    assert decision.kind is PolicyDecisionKind.DENY
    assert decision.reason is PolicyReason.KILLSWITCH_ACTIVE


def test_l0_and_disallowed_risk_fail_closed():
    l0 = AutonomyPolicy(level=AutonomyLevel.L0_CONVERSATION)
    assert l0.decide(_action(), now_ns=1).reason is PolicyReason.CONVERSATION_ONLY
    restricted = AutonomyPolicy(allowed_risks=(ActionRisk.READ,))
    assert (
        restricted.decide(_action(ActionRisk.INSTALL), now_ns=1).reason
        is PolicyReason.RISK_NOT_ALLOWED
    )


def test_policy_decision_receipt_has_stable_content_hash():
    decision = AutonomyPolicy(level=AutonomyLevel.L3_GOAL_SCOPED).decide(
        _action(), now_ns=1
    )
    assert len(decision.content_hash()) == 64
    assert decision.content_hash() == decision.content_hash()
