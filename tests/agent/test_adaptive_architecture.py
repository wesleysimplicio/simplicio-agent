import json
from dataclasses import replace

from agent.adaptive_controller import (
    AdaptiveController,
    AdaptiveProposal,
    ChangeType,
    EvidenceKind,
    ProposalEvidence,
    ProposalRisk,
    SemanticChange,
    Surface,
    Verdict,
)


def _proposal(*, surfaces=(Surface.LOOP,), risk=ProposalRisk.LOW, evidence=()):
    return AdaptiveProposal(
        fingerprint="gap:queue-boundary:v1",
        owner="architecture-owner",
        proposer="coordinator",
        title="Add an independently verifiable intake boundary",
        change_type=ChangeType.ADD_STAGE,
        risk=risk,
        gap="Observed structural gap in intake evidence",
        current_topology="intake -> planner",
        proposed_topology="intake -> evidence-boundary -> planner",
        activation_condition="gap receipt is present",
        success_condition="boundary emits its own receipt",
        authority="Runtime action gate owns effects",
        isolation="read-only proposal context",
        dependencies=("existing intake",),
        compensation_path="discard candidate before promotion",
        affected_components=("intake", "planner"),
        alternatives=("strengthen existing intake hook",),
        migration="coexist until candidate is approved",
        shadow_plan="shadow only",
        canary_plan="policy-selected canary after approval",
        rollback_plan="restore prior versioned candidate",
        kill_switch="disable candidate by fingerprint",
        approval_class="policy",
        surfaces=surfaces,
        semantic_diff=(
            SemanticChange(
                ChangeType.ADD_STAGE,
                "intake",
                "intake -> planner",
                "intake -> evidence-boundary -> planner",
            ),
        ),
        evidence=evidence,
    )


def _evidence(kind, receipt=None, *, status=Verdict.PASS, actor=None, independent=False):
    return ProposalEvidence(
        kind=kind,
        status=status,
        receipt=receipt or f"receipt://442/{kind.value}",
        source="local-test",
        detail="caller-supplied evidence",
        actor=actor,
        independent=independent,
    )


def _complete_evidence(*, runtime=False, approval=False, critical=False):
    values = [_evidence(kind) for kind in (
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
    )]
    if runtime:
        values.append(_evidence(EvidenceKind.RUNTIME))
    if approval:
        count = 2 if critical else 1
        values.extend(
            _evidence(
                EvidenceKind.APPROVAL,
                f"receipt://442/approval/{index}",
                actor=f"independent-reviewer-{index}",
                independent=True,
            )
            for index in range(count)
        )
    return tuple(values)


def test_loop_proposal_passes_only_with_receipt_backed_evidence():
    proposal = _proposal(evidence=_complete_evidence())
    receipt = AdaptiveController().evaluate_proposal(proposal)
    assert receipt.verdict is Verdict.PASS
    assert receipt.promotable
    assert json.loads(json.dumps(receipt.to_dict())) == receipt.to_dict()


def test_agent_requires_runtime_and_missing_evidence_is_unverified():
    proposal = _proposal(
        surfaces=(Surface.AGENT,), evidence=_complete_evidence(runtime=False)
    )
    receipt = AdaptiveController().evaluate_proposal(proposal)
    assert receipt.verdict is Verdict.UNVERIFIED
    assert not receipt.promotable
    assert any(check.name == "runtime" for check in receipt.checks)


def test_failed_evidence_and_duplicate_fingerprint_fail_closed():
    evidence = list(_complete_evidence())
    evidence[0] = _evidence(EvidenceKind.GAP, status=Verdict.FAIL)
    proposal = _proposal(evidence=tuple(evidence))
    receipt = AdaptiveController().evaluate_proposal(
        proposal, existing_fingerprints=(proposal.fingerprint,)
    )
    assert receipt.verdict is Verdict.FAIL
    assert not receipt.promotable


def test_agent_runtime_receipt_allows_pass_without_local_model_path():
    proposal = _proposal(
        surfaces=(Surface.AGENT, Surface.CODE),
        evidence=_complete_evidence(runtime=True),
    )
    receipt = AdaptiveController().evaluate_proposal(proposal)
    assert receipt.verdict is Verdict.PASS


def test_high_risk_requires_independent_approval_and_critical_requires_two():
    high = _proposal(
        risk=ProposalRisk.HIGH,
        evidence=_complete_evidence(approval=True),
    )
    critical_without_two = _proposal(
        risk=ProposalRisk.CRITICAL,
        evidence=_complete_evidence(approval=True, critical=False),
    )
    assert AdaptiveController().evaluate_proposal(high).verdict is Verdict.PASS
    assert (
        AdaptiveController().evaluate_proposal(critical_without_two).verdict
        is Verdict.UNVERIFIED
    )


def test_semantic_diff_mismatch_is_a_structural_failure():
    proposal = _proposal(
        evidence=_complete_evidence(),
    )
    mismatched = replace(
        proposal,
        semantic_diff=(
            SemanticChange(ChangeType.ADD_ROLE, "intake", "old", "new"),
        ),
    )
    assert AdaptiveController().evaluate_proposal(mismatched).verdict is Verdict.FAIL
