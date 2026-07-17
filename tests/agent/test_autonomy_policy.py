"""Focused autonomy policy tests for issue #156."""

import pytest

from agent.autonomy_policy import (
    ActionRequest,
    ActionRisk,
    ApprovalGrant,
    AutonomyLevel,
    AutonomyPolicy,
    AutonomyPolicyError,
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


def test_action_request_rejects_blank_text_fields():
    with pytest.raises(AutonomyPolicyError):
        ActionRequest("   ", "sha256:goal", "workspace:one", ActionRisk.READ)


def test_action_request_accepts_string_risk_and_rejects_bad_mutating():
    action = ActionRequest("sha256:a", "sha256:g", "workspace:one", "read")
    assert action.risk is ActionRisk.READ
    with pytest.raises(TypeError):
        ActionRequest(
            "sha256:a", "sha256:g", "workspace:one", ActionRisk.READ, mutating="yes"
        )


def test_approval_grant_rejects_non_positive_expiry():
    with pytest.raises(AutonomyPolicyError):
        ApprovalGrant("sha256:a", "sha256:g", "workspace:one", 0, "v1")
    with pytest.raises(AutonomyPolicyError):
        ApprovalGrant("sha256:a", "sha256:g", "workspace:one", -5, "v1")


def test_approval_grant_to_dict_and_from_dict_round_trip():
    approval = ApprovalGrant("sha256:a", "sha256:g", "workspace:one", 100, "v1")
    payload = approval.to_dict()
    restored = ApprovalGrant.from_dict(payload)
    assert restored == approval
    assert payload["approved_by"] == "human"


def test_policy_accepts_string_level_and_rejects_duplicate_risk_lists():
    policy = AutonomyPolicy(level="L2")
    assert policy.level is AutonomyLevel.L2_SUPERVISED

    with pytest.raises(AutonomyPolicyError):
        AutonomyPolicy(allowed_risks=(ActionRisk.READ, ActionRisk.READ))

    with pytest.raises(AutonomyPolicyError):
        AutonomyPolicy(
            human_gated_risks=(ActionRisk.DELETE, ActionRisk.DELETE)
        )


def test_policy_rejects_non_bool_killswitch():
    with pytest.raises(TypeError):
        AutonomyPolicy(killswitch="true")


def test_policy_rejects_duplicate_approval_action_digests():
    dup = ApprovalGrant("sha256:same", "sha256:g", "workspace:one", 10, "v1")
    with pytest.raises(AutonomyPolicyError):
        AutonomyPolicy(approvals=(dup, dup))


def test_policy_accepts_approval_dicts_and_normalizes_them():
    payload = {
        "action_digest": "sha256:same",
        "goal_hash": "sha256:g",
        "scope": "workspace:one",
        "expires_at_ns": 10,
        "policy_version": "v1",
        "approved_by": "human",
    }
    policy = AutonomyPolicy(approvals=(payload,))
    assert policy.approvals[0] == ApprovalGrant.from_dict(payload)
