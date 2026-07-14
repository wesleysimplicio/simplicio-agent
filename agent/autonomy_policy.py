"""Profile-scoped autonomy and approval contract (issue #156).

The policy only decides whether an action may proceed.  It does not execute
the action or interpret untrusted page/tool output.  Approval grants are
bound to one action digest, scope, goal, policy version, and expiry so that a
stale approval cannot be reused by another run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Mapping


AUTONOMY_POLICY_SCHEMA = "simplicio.autonomy-policy/v1"


class AutonomyLevel(StrEnum):
    L0_CONVERSATION = "L0"
    L1_SUGGEST = "L1"
    L2_SUPERVISED = "L2"
    L3_GOAL_SCOPED = "L3"
    L4_PERSISTENT = "L4"


class ActionRisk(StrEnum):
    READ = "read"
    REVERSIBLE_WRITE = "reversible_local_write"
    INSTALL = "install"
    PROCESS_EXECUTION = "process_execution"
    EXTERNAL_COMMUNICATION = "external_communication"
    PUBLISH = "publish"
    DELETE = "delete"
    PAYMENT = "payment"
    CREDENTIAL = "credential"
    PRIVILEGE_ESCALATION = "privilege_escalation"


class PolicyDecisionKind(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PolicyReason(StrEnum):
    ALLOWED = "allowed"
    CONVERSATION_ONLY = "conversation_only"
    SUPERVISION_REQUIRED = "supervision_required"
    RISK_NOT_ALLOWED = "risk_not_allowed"
    HUMAN_GATE_REQUIRED = "human_gate_required"
    APPROVAL_ACCEPTED = "approval_accepted"
    APPROVAL_INVALID = "approval_invalid"
    KILLSWITCH_ACTIVE = "killswitch_active"


class AutonomyPolicyError(ValueError):
    """Raised for malformed policy or approval data."""


_DEFAULT_HUMAN_GATES = (
    ActionRisk.EXTERNAL_COMMUNICATION,
    ActionRisk.PUBLISH,
    ActionRisk.DELETE,
    ActionRisk.PAYMENT,
    ActionRisk.CREDENTIAL,
    ActionRisk.PRIVILEGE_ESCALATION,
)


def _text(value: Any, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise AutonomyPolicyError(f"{field} must be non-empty")
    return result


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action_digest: str
    goal_hash: str
    scope: str
    risk: ActionRisk
    mutating: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_digest", _text(self.action_digest, "action_digest")
        )
        object.__setattr__(self, "goal_hash", _text(self.goal_hash, "goal_hash"))
        object.__setattr__(self, "scope", _text(self.scope, "scope"))
        if not isinstance(self.risk, ActionRisk):
            object.__setattr__(self, "risk", ActionRisk(self.risk))
        if not isinstance(self.mutating, bool):
            raise TypeError("mutating must be a boolean")


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """Short-lived approval bound to one exact action contract."""

    action_digest: str
    goal_hash: str
    scope: str
    expires_at_ns: int
    policy_version: str
    approved_by: str = "human"

    def __post_init__(self) -> None:
        for field in (
            "action_digest",
            "goal_hash",
            "scope",
            "policy_version",
            "approved_by",
        ):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if not isinstance(self.expires_at_ns, int) or self.expires_at_ns <= 0:
            raise AutonomyPolicyError("expires_at_ns must be a positive integer")

    def valid_for(
        self, action: ActionRequest, *, policy_version: str, now_ns: int
    ) -> bool:
        return (
            now_ns <= self.expires_at_ns
            and self.policy_version == policy_version
            and self.action_digest == action.action_digest
            and self.goal_hash == action.goal_hash
            and self.scope == action.scope
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_digest": self.action_digest,
            "goal_hash": self.goal_hash,
            "scope": self.scope,
            "expires_at_ns": self.expires_at_ns,
            "policy_version": self.policy_version,
            "approved_by": self.approved_by,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApprovalGrant":
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    kind: PolicyDecisionKind
    reason: PolicyReason
    action_digest: str
    policy_version: str
    approval_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "reason": self.reason.value,
            "action_digest": self.action_digest,
            "policy_version": self.policy_version,
            "approval_used": self.approval_used,
        }


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    """Versioned, explainable, profile-scoped action policy."""

    level: AutonomyLevel = AutonomyLevel.L2_SUPERVISED
    profile_scope: str = "default"
    policy_version: str = AUTONOMY_POLICY_SCHEMA
    allowed_risks: tuple[ActionRisk, ...] = tuple(ActionRisk)
    human_gated_risks: tuple[ActionRisk, ...] = _DEFAULT_HUMAN_GATES
    killswitch: bool = False
    approvals: tuple[ApprovalGrant, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.level, AutonomyLevel):
            object.__setattr__(self, "level", AutonomyLevel(self.level))
        object.__setattr__(
            self, "profile_scope", _text(self.profile_scope, "profile_scope")
        )
        object.__setattr__(
            self, "policy_version", _text(self.policy_version, "policy_version")
        )
        risks = tuple(
            risk if isinstance(risk, ActionRisk) else ActionRisk(risk)
            for risk in self.allowed_risks
        )
        gates = tuple(
            risk if isinstance(risk, ActionRisk) else ActionRisk(risk)
            for risk in self.human_gated_risks
        )
        if len(set(risks)) != len(risks) or len(set(gates)) != len(gates):
            raise AutonomyPolicyError("risk lists must not contain duplicates")
        object.__setattr__(self, "allowed_risks", risks)
        object.__setattr__(self, "human_gated_risks", gates)
        if not isinstance(self.killswitch, bool):
            raise TypeError("killswitch must be a boolean")
        approvals = tuple(
            item if isinstance(item, ApprovalGrant) else ApprovalGrant.from_dict(item)
            for item in self.approvals
        )
        if len({item.action_digest for item in approvals}) != len(approvals):
            raise AutonomyPolicyError(
                "approvals must not contain duplicate action digests"
            )
        object.__setattr__(self, "approvals", approvals)

    def with_killswitch(self, active: bool = True) -> "AutonomyPolicy":
        return replace(self, killswitch=active)

    def decide(
        self,
        action: ActionRequest,
        *,
        now_ns: int,
        approval: ApprovalGrant | None = None,
    ) -> PolicyDecision:
        if self.killswitch:
            return PolicyDecision(
                PolicyDecisionKind.DENY,
                PolicyReason.KILLSWITCH_ACTIVE,
                action.action_digest,
                self.policy_version,
            )
        if action.risk not in self.allowed_risks:
            return PolicyDecision(
                PolicyDecisionKind.DENY,
                PolicyReason.RISK_NOT_ALLOWED,
                action.action_digest,
                self.policy_version,
            )
        if approval is not None and approval.valid_for(
            action, policy_version=self.policy_version, now_ns=now_ns
        ):
            return PolicyDecision(
                PolicyDecisionKind.ALLOW,
                PolicyReason.APPROVAL_ACCEPTED,
                action.action_digest,
                self.policy_version,
                True,
            )
        if self.level is AutonomyLevel.L0_CONVERSATION:
            return PolicyDecision(
                PolicyDecisionKind.DENY,
                PolicyReason.CONVERSATION_ONLY,
                action.action_digest,
                self.policy_version,
            )
        if self.level is AutonomyLevel.L1_SUGGEST:
            return PolicyDecision(
                PolicyDecisionKind.ASK,
                PolicyReason.SUPERVISION_REQUIRED,
                action.action_digest,
                self.policy_version,
            )
        if self.level is AutonomyLevel.L2_SUPERVISED and (
            action.mutating or action.risk is not ActionRisk.READ
        ):
            return PolicyDecision(
                PolicyDecisionKind.ASK,
                PolicyReason.SUPERVISION_REQUIRED,
                action.action_digest,
                self.policy_version,
            )
        if action.risk in self.human_gated_risks:
            return PolicyDecision(
                PolicyDecisionKind.ASK,
                PolicyReason.HUMAN_GATE_REQUIRED,
                action.action_digest,
                self.policy_version,
            )
        return PolicyDecision(
            PolicyDecisionKind.ALLOW,
            PolicyReason.ALLOWED,
            action.action_digest,
            self.policy_version,
        )

    def explain(self) -> dict[str, Any]:
        return {
            "schema": AUTONOMY_POLICY_SCHEMA,
            "level": self.level.value,
            "profile_scope": self.profile_scope,
            "policy_version": self.policy_version,
            "allowed_risks": [risk.value for risk in self.allowed_risks],
            "human_gated_risks": [risk.value for risk in self.human_gated_risks],
            "killswitch": self.killswitch,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(
            self.explain(), sort_keys=True, ensure_ascii=False, indent=indent
        )


__all__ = [
    "AUTONOMY_POLICY_SCHEMA",
    "AutonomyLevel",
    "ActionRisk",
    "PolicyDecisionKind",
    "PolicyReason",
    "ActionRequest",
    "ApprovalGrant",
    "PolicyDecision",
    "AutonomyPolicy",
    "AutonomyPolicyError",
]
