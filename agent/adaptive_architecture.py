"""Proposal/evidence gate for the existing adaptive controller.

This module is deliberately a passive contract.  It records a topology
proposal and evaluates caller-supplied evidence; it does not execute a stage,
change a graph, schedule work, open an issue, or promote a candidate.

Agent and Code surfaces require a verified Runtime receipt.  Loop is the only
standalone surface.  Missing evidence is ``UNVERIFIED`` and therefore never
authorizes promotion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


PROPOSAL_SCHEMA = "simplicio.adaptive-proposal/v1"
EVIDENCE_SCHEMA = "simplicio.adaptive-evidence/v1"
GATE_SCHEMA = "simplicio.adaptive-gate/v1"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class ChangeType(StrEnum):
    ADD_STAGE = "add_stage"
    REMOVE_STAGE = "remove_stage"
    SPLIT_STAGE = "split_stage"
    MERGE_STAGE = "merge_stage"
    REORDER_STAGE = "reorder_stage"
    ADD_ROLE = "add_role"
    CHANGE_ROLE = "change_role"
    CHANGE_ACTIVATION = "change_activation"
    CHANGE_DEPENDENCY = "change_dependency"
    CHANGE_ISOLATION = "change_isolation"
    ADD_GATE = "add_gate"
    STRENGTHEN_GATE = "strengthen_gate"
    WEAKEN_GATE = "weaken_gate"
    CHANGE_RETRY = "change_retry"
    CHANGE_TIMEOUT = "change_timeout"
    CHANGE_CAPACITY = "change_capacity"
    CHANGE_WAVE = "change_wave"
    ADD_ADAPTER = "add_adapter"
    ADD_RECEIPT = "add_receipt"
    ADD_SUBFLOW = "add_subflow"
    DEPRECATE_COMPONENT = "deprecate_component"


class ProposalRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Surface(StrEnum):
    LOOP = "Loop"
    AGENT = "Agent"
    CODE = "Code"


class EvidenceKind(StrEnum):
    GAP = "gap"
    BASELINE = "baseline"
    BOUNDARY = "boundary"
    ACTIVATION = "activation"
    SUCCESS = "success"
    OWNER = "owner"
    AUTHORITY = "authority"
    DEPENDENCY = "dependency"
    COMPENSATION = "compensation"
    ISOLATION = "isolation"
    NECESSITY = "necessity"
    COST = "cost"
    FALLBACK = "fallback"
    ROLLBACK = "rollback"
    SEMANTIC_DIFF = "semantic_diff"
    STATIC_VALIDATION = "static_validation"
    SIMULATION = "simulation"
    REPLAY = "replay"
    SHADOW = "shadow"
    APPROVAL = "approval"
    RUNTIME = "runtime"


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _enum(value: object, enum_type: type[StrEnum], field: str) -> StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc


@dataclass(frozen=True, slots=True)
class ProposalEvidence:
    """One externally produced evidence item.

    A receipt is an opaque reference.  This contract does not infer or
    calculate metrics from ``detail`` and does not treat prose as proof.
    """

    kind: EvidenceKind
    status: Verdict
    receipt: str | None = None
    source: str = ""
    detail: str = ""
    actor: str | None = None
    independent: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, EvidenceKind, "evidence kind"))
        object.__setattr__(self, "status", _enum(self.status, Verdict, "evidence status"))
        if self.receipt is not None:
            object.__setattr__(self, "receipt", _text(self.receipt, "evidence receipt"))
        if self.source:
            object.__setattr__(self, "source", _text(self.source, "evidence source"))
        if self.actor is not None:
            object.__setattr__(self, "actor", _text(self.actor, "evidence actor"))
        if not isinstance(self.independent, bool):
            raise TypeError("evidence independent must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": EVIDENCE_SCHEMA,
            "kind": self.kind.value,
            "status": self.status.value,
            "receipt": self.receipt,
            "source": self.source,
            "detail": self.detail,
            "actor": self.actor,
            "independent": self.independent,
        }


@dataclass(frozen=True, slots=True)
class SemanticChange:
    """A declarative change entry; it is not a graph operation."""

    change_type: ChangeType
    target: str
    before: str
    after: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_type", _enum(self.change_type, ChangeType, "change type"))
        for field in ("target", "before", "after"):
            object.__setattr__(self, field, _text(getattr(self, field), field))

    def to_dict(self) -> dict[str, str]:
        return {
            "change_type": self.change_type.value,
            "target": self.target,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True, slots=True)
class AdaptiveProposal:
    """Immutable RFC-shaped proposal emitted by the existing controller."""

    fingerprint: str
    owner: str
    proposer: str
    title: str
    change_type: ChangeType
    risk: ProposalRisk
    gap: str
    current_topology: str
    proposed_topology: str
    activation_condition: str
    success_condition: str
    authority: str
    isolation: str
    dependencies: tuple[str, ...] = ()
    compensation_path: str = ""
    affected_components: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    migration: str = ""
    shadow_plan: str = ""
    canary_plan: str = ""
    rollback_plan: str = ""
    kill_switch: str = ""
    approval_class: str = ""
    surfaces: tuple[Surface, ...] = (Surface.LOOP,)
    semantic_diff: tuple[SemanticChange, ...] = ()
    evidence: tuple[ProposalEvidence, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "fingerprint",
            "owner",
            "proposer",
            "title",
            "gap",
            "current_topology",
            "proposed_topology",
            "activation_condition",
            "success_condition",
            "authority",
            "isolation",
        ):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "change_type", _enum(self.change_type, ChangeType, "change type"))
        object.__setattr__(self, "risk", _enum(self.risk, ProposalRisk, "risk"))
        object.__setattr__(
            self,
            "surfaces",
            tuple(_enum(item, Surface, "surface") for item in self.surfaces),
        )
        object.__setattr__(
            self,
            "semantic_diff",
            tuple(item if isinstance(item, SemanticChange) else SemanticChange(**item) for item in self.semantic_diff),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(item if isinstance(item, ProposalEvidence) else ProposalEvidence(**item) for item in self.evidence),
        )
        for field in (
            "dependencies",
            "affected_components",
            "alternatives",
        ):
            values = tuple(_text(item, field) for item in getattr(self, field))
            object.__setattr__(self, field, values)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PROPOSAL_SCHEMA,
            "fingerprint": self.fingerprint,
            "owner": self.owner,
            "proposer": self.proposer,
            "title": self.title,
            "change_type": self.change_type.value,
            "risk": self.risk.value,
            "gap": self.gap,
            "current_topology": self.current_topology,
            "proposed_topology": self.proposed_topology,
            "activation_condition": self.activation_condition,
            "success_condition": self.success_condition,
            "authority": self.authority,
            "isolation": self.isolation,
            "dependencies": list(self.dependencies),
            "compensation_path": self.compensation_path,
            "affected_components": list(self.affected_components),
            "alternatives": list(self.alternatives),
            "migration": self.migration,
            "shadow_plan": self.shadow_plan,
            "canary_plan": self.canary_plan,
            "rollback_plan": self.rollback_plan,
            "kill_switch": self.kill_switch,
            "approval_class": self.approval_class,
            "surfaces": [item.value for item in self.surfaces],
            "semantic_diff": [item.to_dict() for item in self.semantic_diff],
            "evidence": [item.to_dict() for item in self.evidence],
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    verdict: Verdict
    reason: str
    receipts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "receipts": list(self.receipts),
        }


@dataclass(frozen=True, slots=True)
class ProposalGateReceipt:
    """Machine-readable gate outcome; PASS is the only promotable result."""

    proposal_hash: str
    verdict: Verdict
    checks: tuple[GateCheck, ...]

    @property
    def promotable(self) -> bool:
        return self.verdict is Verdict.PASS

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": GATE_SCHEMA,
            "proposal_hash": self.proposal_hash,
            "verdict": self.verdict.value,
            "promotable": self.promotable,
            "checks": [check.to_dict() for check in self.checks],
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_BASE_REQUIRED = (
    EvidenceKind.GAP,
    EvidenceKind.BASELINE,
    EvidenceKind.BOUNDARY,
    EvidenceKind.ACTIVATION,
    EvidenceKind.SUCCESS,
    EvidenceKind.OWNER,
    EvidenceKind.AUTHORITY,
    EvidenceKind.DEPENDENCY,
    EvidenceKind.COMPENSATION,
    EvidenceKind.ISOLATION,
    EvidenceKind.NECESSITY,
    EvidenceKind.COST,
    EvidenceKind.FALLBACK,
    EvidenceKind.ROLLBACK,
    EvidenceKind.SEMANTIC_DIFF,
    EvidenceKind.STATIC_VALIDATION,
    EvidenceKind.SHADOW,
)


def _evidence_check(
    kind: EvidenceKind,
    evidence: dict[EvidenceKind, tuple[ProposalEvidence, ...]],
) -> GateCheck:
    items = evidence.get(kind, ())
    if not items:
        return GateCheck(kind.value, Verdict.UNVERIFIED, "required evidence is missing")
    if any(item.status is Verdict.FAIL for item in items):
        return GateCheck(
            kind.value,
            Verdict.FAIL,
            "evidence reported FAIL",
            tuple(item.receipt for item in items if item.receipt),
        )
    if any(item.status is not Verdict.PASS or not item.receipt for item in items):
        return GateCheck(
            kind.value,
            Verdict.UNVERIFIED,
            "evidence is not receipt-backed PASS",
            tuple(item.receipt for item in items if item.receipt),
        )
    return GateCheck(
        kind.value,
        Verdict.PASS,
        "receipt-backed evidence verified",
        tuple(item.receipt for item in items if item.receipt),
    )


def evaluate_proposal_gate(
    proposal: AdaptiveProposal,
    *,
    existing_fingerprints: Iterable[str] = (),
) -> ProposalGateReceipt:
    """Evaluate a proposal without executing or mutating anything.

    The gate is intentionally conservative: malformed structure is FAIL,
    missing/stale/unverified external evidence is UNVERIFIED, and only a
    complete set of receipt-backed PASS checks can be promoted by a caller.
    """

    if not isinstance(proposal, AdaptiveProposal):
        raise TypeError("proposal must be an AdaptiveProposal")

    checks: list[GateCheck] = []
    known = {str(value).strip() for value in existing_fingerprints if str(value).strip()}
    if proposal.fingerprint in known:
        checks.append(GateCheck("dedup", Verdict.FAIL, "fingerprint already exists"))
    else:
        checks.append(GateCheck("dedup", Verdict.PASS, "fingerprint is new"))

    if not proposal.semantic_diff:
        checks.append(GateCheck("proposal_shape", Verdict.FAIL, "semantic diff is empty"))
    elif any(item.change_type is not proposal.change_type for item in proposal.semantic_diff):
        checks.append(GateCheck("proposal_shape", Verdict.FAIL, "semantic diff type does not match proposal"))
    else:
        checks.append(GateCheck("proposal_shape", Verdict.PASS, "proposal shape is bounded and typed"))

    evidence = {kind: tuple(item for item in proposal.evidence if item.kind is kind) for kind in EvidenceKind}
    for kind in _BASE_REQUIRED:
        checks.append(_evidence_check(kind, evidence))

    if Surface.AGENT in proposal.surfaces or Surface.CODE in proposal.surfaces:
        checks.append(_evidence_check(EvidenceKind.RUNTIME, evidence))
    else:
        checks.append(GateCheck("runtime", Verdict.PASS, "Loop is standalone; Runtime receipt is not required"))

    approvals = evidence.get(EvidenceKind.APPROVAL, ())
    if proposal.risk is ProposalRisk.LOW:
        checks.append(GateCheck("approval", Verdict.PASS, "low-risk proposal uses policy approval class"))
    else:
        required = 2 if proposal.risk is ProposalRisk.CRITICAL else 1
        valid_approvals = tuple(
            item
            for item in approvals
            if item.status is Verdict.PASS
            and item.receipt
            and item.independent
            and item.actor
            and item.actor not in {proposal.owner, proposal.proposer}
        )
        if len(valid_approvals) < required:
            checks.append(
                GateCheck(
                    "approval",
                    Verdict.UNVERIFIED,
                    f"{required} independent receipt-backed approval(s) required",
                    tuple(item.receipt for item in valid_approvals if item.receipt),
                )
            )
        else:
            checks.append(
                GateCheck(
                    "approval",
                    Verdict.PASS,
                    "independent approval is receipt-backed",
                    tuple(item.receipt for item in valid_approvals if item.receipt),
                )
            )

    verdict = (
        Verdict.FAIL
        if any(check.verdict is Verdict.FAIL for check in checks)
        else Verdict.UNVERIFIED
        if any(check.verdict is Verdict.UNVERIFIED for check in checks)
        else Verdict.PASS
    )
    return ProposalGateReceipt(proposal.content_hash(), verdict, tuple(checks))


__all__ = [
    "AdaptiveProposal",
    "ChangeType",
    "EvidenceKind",
    "EVIDENCE_SCHEMA",
    "GATE_SCHEMA",
    "GateCheck",
    "ProposalEvidence",
    "ProposalGateReceipt",
    "ProposalRisk",
    "PROPOSAL_SCHEMA",
    "SemanticChange",
    "Surface",
    "Verdict",
    "evaluate_proposal_gate",
]
