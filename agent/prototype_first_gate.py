"""Prototype-First Gate cognitive layer (issue #484, loop epic #568).

This module gives the Simplicio Agent a deterministic, schema-validated
pipeline for the Prototype-First Gate: a **planner** proposes a bounded
hypothesis, **candidate creators** produce genuinely distinct approaches, an
adversarial **critic/safety** pass looks for injected defects (missing
evidence, unfounded claims, scope drift), and an **independent judge** scores
and decides ACCEPT / REVISE / REJECT.  An optional **synthesizer** may combine
only mutually compatible candidates and forces a full revalidation of the
merged artifact.

Hard invariants enforced by this contract, not by convention:

* **No delivery authority.**  Every role is instantiated with an explicit
  capability allowlist; any capability that looks like a promote/deliver/
  publish/write-to-target action is rejected at construction time
  (:class:`ForbiddenCapabilityError`).
* **Self-judging is impossible.**  If the judge's identity matches the
  creator identity of any candidate under review, the pipeline refuses to
  emit a decision at all (:class:`SelfJudgingError`) rather than silently
  degrading to a biased verdict.
* **Diversity is measured, not assumed.**  Candidates declare structured
  ``approach_tags``/``operations`` (not free prose); diversity is a real
  Jaccard-distance computation over those structured facts.
* **ACCEPT requires evidence, not plausibility.**  A candidate can only be
  accepted when every required acceptance-criterion id is covered by a claim
  that itself carries at least one evidence handle, and the critic recorded
  zero unresolved findings.
* **REVISE is bounded and stall-detected.**  The loop never runs forever: a
  fixed round cap and a stagnation check on the leading score both terminate
  it with an auditable reason.

Everything here is pure and deterministic: no LLM calls, no network I/O, no
filesystem access.  Generating the actual prototype content (the LLM
reasoning behind a candidate) is out of scope for this contract; it validates
and adjudicates whatever structured artifacts the roles produce.

Out of scope for this pass (see issue #484): remote-escalation-by-confidence
routing, prompt-injection adversarial fuzzing, and cross-repo conformance
with the upstream simplicio-loop/Mapper/Runtime packages.  If the upstream
``simplicio-loop`` ``prototype-plan/v1`` package becomes importable, this
module's schema constants should be reconciled with it; until then this is a
local mirror.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


PLAN_SCHEMA_VERSION = "simplicio.prototype-plan/v1"
CANDIDATE_SCHEMA_VERSION = "simplicio.prototype-candidate/v1"
CRITIC_SCHEMA_VERSION = "simplicio.prototype-critic/v1"
JUDGE_SCHEMA_VERSION = "simplicio.prototype-judge/v1"
DECISION_SCHEMA_VERSION = "simplicio.prototype-decision/v1"
GATE_SCHEMA_VERSION = "simplicio.prototype-gate/v1"

#: Minimum number of genuinely distinct candidates a round must contain.
MIN_CANDIDATES = 2
#: Ceiling on candidates per round (keeps judge comparison bounded).
MAX_CANDIDATES = 8
#: Bounded REVISE ceiling — the loop never iterates past this many rounds.
MAX_REVISE_ROUNDS = 3
#: Mean pairwise Jaccard distance below this is flagged as low diversity.
DIVERSITY_WARNING_THRESHOLD = 0.35
#: Minimum score improvement between rounds to NOT count as stalled.
STALL_EPSILON = 1e-9

#: Capability substrings that grant delivery/promotion authority.  No role in
#: this contract may ever declare a capability containing one of these
#: tokens — the gate only recommends; it never ships.
FORBIDDEN_CAPABILITY_TOKENS = (
    "promote",
    "deliver",
    "publish",
    "release",
    "merge",
    "write_to_target",
    "write-to-target",
    "deploy",
    "push_to_prod",
)


class ForbiddenCapabilityError(ValueError):
    """Raised when a role is instantiated with delivery/promotion authority."""


class SelfJudgingError(ValueError):
    """Raised when a judge's identity matches a candidate creator's identity."""


class RoleKind(str, Enum):
    PLANNER = "planner"
    CREATOR = "creator"
    CRITIC = "critic"
    JUDGE = "judge"
    SYNTHESIZER = "synthesizer"


class DefectClass(str, Enum):
    MISSING_EVIDENCE = "missing_evidence"
    UNFOUNDED_CLAIM = "unfounded_claim"
    SCOPE_DRIFT = "scope_drift"


class DecisionKind(str, Enum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"


def _text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _texts(values: Iterable[Any], field_name: str) -> tuple[str, ...]:
    return tuple(sorted({_text(value, field_name) for value in values}))


def _unit_interval(value: Any, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return number


def _non_negative(value: Any, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return number


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _check_forbidden_capabilities(capabilities: tuple[str, ...]) -> None:
    lowered = [capability.lower() for capability in capabilities]
    hits = sorted(
        {
            capability
            for capability in lowered
            for token in FORBIDDEN_CAPABILITY_TOKENS
            if token in capability
        }
    )
    if hits:
        raise ForbiddenCapabilityError(
            "role capability allowlist includes delivery/promotion authority: "
            + ", ".join(hits)
        )


@dataclass(frozen=True, slots=True)
class RoleIdentity:
    """Identity + capability allowlist for one Prototype-First Gate role.

    Construction itself is the enforcement point for "no delivery
    authority" — any capability that looks like promote/deliver/publish/
    write-to-target raises :class:`ForbiddenCapabilityError` immediately.
    """

    identity: str
    role: RoleKind
    capabilities: tuple[str, ...] = ()
    lane: str = "fast"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", _text(self.identity, "identity"))
        if not isinstance(self.role, RoleKind):
            object.__setattr__(self, "role", RoleKind(self.role))
        object.__setattr__(
            self, "capabilities", _texts(self.capabilities, "capabilities")
        )
        object.__setattr__(self, "lane", _text(self.lane, "lane"))
        if self.lane not in ("fast", "slow", "background"):
            raise ValueError("lane must be one of: fast, slow, background")
        _check_forbidden_capabilities(self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "role": self.role.value,
            "capabilities": list(self.capabilities),
            "lane": self.lane,
        }


@dataclass(frozen=True, slots=True)
class PrototypePlan:
    """Prototype Planner output: hypothesis, level, budgets, validators."""

    hypothesis: str
    level: str
    candidate_types: tuple[str, ...]
    budgets: Mapping[str, float]
    validators: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    planner: RoleIdentity
    allowed_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "hypothesis", _text(self.hypothesis, "hypothesis"))
        object.__setattr__(self, "level", _text(self.level, "level"))
        if self.level not in ("micro", "spike", "prototype"):
            raise ValueError("level must be one of: micro, spike, prototype")
        object.__setattr__(
            self, "candidate_types", _texts(self.candidate_types, "candidate_types")
        )
        if len(self.candidate_types) < 1:
            raise ValueError("candidate_types must declare at least 1 approach type")
        budgets = {
            _text(key, "budgets key"): _non_negative(value, f"budgets[{key}]")
            for key, value in dict(self.budgets).items()
        }
        object.__setattr__(self, "budgets", budgets)
        object.__setattr__(
            self, "validators", _texts(self.validators, "validators")
        )
        acceptance_criteria = _texts(
            self.acceptance_criteria, "acceptance_criteria"
        )
        if not acceptance_criteria:
            raise ValueError("acceptance_criteria must be non-empty")
        object.__setattr__(self, "acceptance_criteria", acceptance_criteria)
        object.__setattr__(
            self, "allowed_scope", _texts(self.allowed_scope, "allowed_scope")
        )
        if self.planner.role is not RoleKind.PLANNER:
            raise ValueError("planner identity must declare role=planner")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "hypothesis": self.hypothesis,
            "level": self.level,
            "candidate_types": list(self.candidate_types),
            "budgets": dict(self.budgets),
            "validators": list(self.validators),
            "acceptance_criteria": list(self.acceptance_criteria),
            "allowed_scope": list(self.allowed_scope),
            "planner": self.planner.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Claim:
    """One explicit claim a candidate makes, with (or without) evidence."""

    claim_id: str
    statement: str
    evidence_handles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self,
            "evidence_handles",
            _texts(self.evidence_handles, "evidence_handles"),
        )

    @property
    def has_evidence(self) -> bool:
        return len(self.evidence_handles) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "evidence_handles": list(self.evidence_handles),
        }


@dataclass(frozen=True, slots=True)
class PrototypeCandidate:
    """One candidate approach produced by a Candidate Agent (creator)."""

    approach_id: str
    creator: RoleIdentity
    approach_tags: tuple[str, ...]
    operations: tuple[str, ...]
    claims: tuple[Claim, ...]
    ac_covered: tuple[str, ...]
    declared_scope: tuple[str, ...]
    cost_estimate: float
    risk_estimate: float
    reversibility: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "approach_id", _text(self.approach_id, "approach_id"))
        if self.creator.role not in (RoleKind.CREATOR, RoleKind.SYNTHESIZER):
            raise ValueError(
                "creator identity must declare role=creator (or role=synthesizer "
                "for a synthesized artifact)"
            )
        approach_tags = _texts(self.approach_tags, "approach_tags")
        if not approach_tags:
            raise ValueError("approach_tags must be non-empty")
        object.__setattr__(self, "approach_tags", approach_tags)
        object.__setattr__(self, "operations", _texts(self.operations, "operations"))
        claims = tuple(
            sorted(self.claims, key=lambda claim: claim.claim_id)
        )
        claim_ids = [claim.claim_id for claim in claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim_id values must be unique")
        object.__setattr__(self, "claims", claims)
        object.__setattr__(
            self, "ac_covered", _texts(self.ac_covered, "ac_covered")
        )
        object.__setattr__(
            self, "declared_scope", _texts(self.declared_scope, "declared_scope")
        )
        object.__setattr__(
            self, "cost_estimate", _non_negative(self.cost_estimate, "cost_estimate")
        )
        object.__setattr__(
            self, "risk_estimate", _unit_interval(self.risk_estimate, "risk_estimate")
        )
        object.__setattr__(
            self,
            "reversibility",
            _unit_interval(self.reversibility, "reversibility"),
        )

    @property
    def diversity_features(self) -> frozenset[str]:
        """Structured facts used for the diversity metric — never prose."""

        return frozenset(self.approach_tags) | frozenset(
            f"op:{operation}" for operation in self.operations
        )

    @property
    def evidence_handles(self) -> tuple[str, ...]:
        handles: set[str] = set()
        for claim in self.claims:
            handles.update(claim.evidence_handles)
        return tuple(sorted(handles))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "approach_id": self.approach_id,
            "creator": self.creator.to_dict(),
            "approach_tags": list(self.approach_tags),
            "operations": list(self.operations),
            "claims": [claim.to_dict() for claim in self.claims],
            "ac_covered": list(self.ac_covered),
            "declared_scope": list(self.declared_scope),
            "cost_estimate": self.cost_estimate,
            "risk_estimate": self.risk_estimate,
            "reversibility": self.reversibility,
        }


def _jaccard_distance(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    intersection = left & right
    similarity = len(intersection) / len(union)
    return 1.0 - similarity


@dataclass(frozen=True, slots=True)
class DiversityPair:
    left_id: str
    right_id: str
    distance: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_id": self.left_id,
            "right_id": self.right_id,
            "distance": self.distance,
        }


@dataclass(frozen=True, slots=True)
class DiversityReport:
    """Real, measured diversity across a candidate round — never assumed."""

    pairs: tuple[DiversityPair, ...]
    mean_distance: float
    low_diversity_pairs: tuple[str, ...]
    warning: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pairs": [pair.to_dict() for pair in self.pairs],
            "mean_distance": self.mean_distance,
            "low_diversity_pairs": list(self.low_diversity_pairs),
            "warning": self.warning,
        }


def measure_diversity(
    candidates: Sequence[PrototypeCandidate],
    *,
    warning_threshold: float = DIVERSITY_WARNING_THRESHOLD,
) -> DiversityReport:
    """Compute real pairwise Jaccard distance over structured candidate facts.

    This is a measurement, not an assumption: two candidates that only differ
    in prompt wording but declare the same ``approach_tags``/``operations``
    collapse to distance 0 and trigger the low-diversity warning; genuinely
    different approaches (different tags/operations) score higher.
    """

    ordered = sorted(candidates, key=lambda candidate: candidate.approach_id)
    if len(ordered) < MIN_CANDIDATES:
        raise ValueError(
            f"a candidate round must contain at least {MIN_CANDIDATES} candidates"
        )
    if len(ordered) > MAX_CANDIDATES:
        raise ValueError(f"candidate round exceeds MAX_CANDIDATES={MAX_CANDIDATES}")

    pairs: list[DiversityPair] = []
    low_pairs: list[str] = []
    total = 0.0
    count = 0
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            left = ordered[i]
            right = ordered[j]
            distance = _jaccard_distance(
                left.diversity_features, right.diversity_features
            )
            pairs.append(
                DiversityPair(left.approach_id, right.approach_id, distance)
            )
            total += distance
            count += 1
            if distance < warning_threshold:
                low_pairs.append(f"{left.approach_id}:{right.approach_id}")

    mean_distance = total / count if count else 0.0
    return DiversityReport(
        pairs=tuple(pairs),
        mean_distance=mean_distance,
        low_diversity_pairs=tuple(sorted(low_pairs)),
        warning=mean_distance < warning_threshold or bool(low_pairs),
    )


@dataclass(frozen=True, slots=True)
class CriticFinding:
    defect_class: DefectClass
    detail: str
    related_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "defect_class": self.defect_class.value,
            "detail": self.detail,
            "related_id": self.related_id,
        }


@dataclass(frozen=True, slots=True)
class CriticReport:
    approach_id: str
    critic: RoleIdentity
    findings: tuple[CriticFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CRITIC_SCHEMA_VERSION,
            "approach_id": self.approach_id,
            "critic": self.critic.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def review_candidate(
    plan: PrototypePlan,
    candidate: PrototypeCandidate,
    critic: RoleIdentity,
) -> CriticReport:
    """Adversarially review one candidate for injected defects.

    Deterministically detects three defect classes from structured facts —
    never free-text sentiment:

    * ``MISSING_EVIDENCE`` — an acceptance-criterion id the candidate claims
      to cover has no claim referencing it, or that claim carries zero
      evidence handles.
    * ``UNFOUNDED_CLAIM`` — any claim (regardless of AC linkage) with zero
      evidence handles.
    * ``SCOPE_DRIFT`` — a declared-scope path outside the plan's
      ``allowed_scope`` prefixes (when the plan declares a scope at all).
    """

    if critic.role is not RoleKind.CRITIC:
        raise ValueError("critic identity must declare role=critic")

    findings: list[CriticFinding] = []

    claims_by_ac: dict[str, list[Claim]] = {}
    for claim in candidate.claims:
        if not claim.has_evidence:
            findings.append(
                CriticFinding(
                    DefectClass.UNFOUNDED_CLAIM,
                    "claim carries zero evidence handles",
                    claim.claim_id,
                )
            )

    for ac_id in candidate.ac_covered:
        # A claim "covers" an AC id when its claim_id equals the AC id, or
        # when the AC id appears in the claim's evidence handles namespace.
        # The plan owns the mapping; the candidate must be explicit.
        matching = [claim for claim in candidate.claims if claim.claim_id == ac_id]
        if not matching:
            findings.append(
                CriticFinding(
                    DefectClass.MISSING_EVIDENCE,
                    "acceptance criterion claimed covered but no matching claim exists",
                    ac_id,
                )
            )
            continue
        if not any(claim.has_evidence for claim in matching):
            findings.append(
                CriticFinding(
                    DefectClass.MISSING_EVIDENCE,
                    "acceptance criterion's claim has zero evidence handles",
                    ac_id,
                )
            )
        claims_by_ac[ac_id] = matching

    if plan.allowed_scope:
        for path in candidate.declared_scope:
            if not any(
                path == allowed or path.startswith(allowed.rstrip("/") + "/")
                for allowed in plan.allowed_scope
            ):
                findings.append(
                    CriticFinding(
                        DefectClass.SCOPE_DRIFT,
                        "declared scope path is outside the plan's allowed_scope",
                        path,
                    )
                )

    return CriticReport(
        approach_id=candidate.approach_id,
        critic=critic,
        findings=tuple(
            sorted(findings, key=lambda finding: (finding.defect_class.value, finding.related_id))
        ),
    )


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Deterministic, explainable score for one candidate."""

    approach_id: str
    ac_coverage_ratio: float
    evidence_present: bool
    critic_finding_count: int
    score: float
    breakdown: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "approach_id": self.approach_id,
            "ac_coverage_ratio": self.ac_coverage_ratio,
            "evidence_present": self.evidence_present,
            "critic_finding_count": self.critic_finding_count,
            "score": self.score,
            "breakdown": dict(self.breakdown),
        }

    @property
    def eligible_for_accept(self) -> bool:
        """AC coverage + evidence + zero findings — never just "looks plausible"."""

        return (
            self.ac_coverage_ratio >= 1.0
            and self.evidence_present
            and self.critic_finding_count == 0
        )


# Explainable, fixed weights — documented here instead of buried in the math.
JUDGE_WEIGHTS: Mapping[str, float] = {
    "ac_coverage": 0.40,
    "evidence": 0.15,
    "cost": 0.15,
    "risk": 0.15,
    "reversibility": 0.15,
}
JUDGE_FINDING_PENALTY = 0.10


def score_candidate(
    plan: PrototypePlan,
    candidate: PrototypeCandidate,
    critic_report: CriticReport,
    *,
    max_cost: float,
) -> JudgeVerdict:
    required = set(plan.acceptance_criteria)
    covered = required & set(candidate.ac_covered)
    ac_coverage_ratio = len(covered) / len(required) if required else 0.0

    evidence_present = len(candidate.evidence_handles) > 0
    evidence_component = 1.0 if evidence_present else 0.0

    normalized_cost = (
        candidate.cost_estimate / max_cost if max_cost > 0 else 0.0
    )
    normalized_cost = min(1.0, normalized_cost)
    cost_component = 1.0 - normalized_cost
    risk_component = 1.0 - candidate.risk_estimate
    reversibility_component = candidate.reversibility

    breakdown = {
        "ac_coverage": JUDGE_WEIGHTS["ac_coverage"] * ac_coverage_ratio,
        "evidence": JUDGE_WEIGHTS["evidence"] * evidence_component,
        "cost": JUDGE_WEIGHTS["cost"] * cost_component,
        "risk": JUDGE_WEIGHTS["risk"] * risk_component,
        "reversibility": JUDGE_WEIGHTS["reversibility"] * reversibility_component,
    }
    finding_count = len(critic_report.findings)
    penalty = JUDGE_FINDING_PENALTY * finding_count
    breakdown["critic_penalty"] = -penalty

    score = sum(breakdown.values())
    return JudgeVerdict(
        approach_id=candidate.approach_id,
        ac_coverage_ratio=ac_coverage_ratio,
        evidence_present=evidence_present,
        critic_finding_count=finding_count,
        score=score,
        breakdown=breakdown,
    )


def assert_no_self_judging(
    judge: RoleIdentity, candidates: Sequence[PrototypeCandidate]
) -> None:
    """Hard-block self-judging: a candidate's own creator can never judge it.

    Raises :class:`SelfJudgingError` and refuses to emit ANY decision — for
    the whole round, not just the affected candidate — when the judge's
    identity matches any candidate's creator identity.
    """

    if judge.role is not RoleKind.JUDGE:
        raise ValueError("judge identity must declare role=judge")
    creator_identities = {candidate.creator.identity for candidate in candidates}
    if judge.identity in creator_identities:
        raise SelfJudgingError(
            "self-judging blocked: judge identity "
            f"{judge.identity!r} matches a candidate creator identity"
        )


@dataclass(frozen=True, slots=True)
class PrototypeDecision:
    kind: DecisionKind
    reason: str
    round_number: int
    winner_approach_id: str | None
    verdicts: tuple[JudgeVerdict, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_SCHEMA_VERSION,
            "kind": self.kind.value,
            "reason": self.reason,
            "round_number": self.round_number,
            "winner_approach_id": self.winner_approach_id,
            "verdicts": [verdict.to_dict() for verdict in self.verdicts],
        }


def decide_round(
    plan: PrototypePlan,
    candidates: Sequence[PrototypeCandidate],
    judge: RoleIdentity,
    critic: RoleIdentity,
    *,
    round_number: int,
) -> tuple[PrototypeDecision, tuple[CriticReport, ...], DiversityReport]:
    """Run critic + judge over one round and return a bounded decision.

    This does not loop — callers drive :func:`run_bounded_revise` (or their
    own loop) to feed successive rounds.  Self-judging is checked first and
    raises rather than degrading into a biased decision.
    """

    assert_no_self_judging(judge, candidates)
    diversity = measure_diversity(candidates)

    critic_reports = tuple(
        review_candidate(plan, candidate, critic) for candidate in candidates
    )
    critic_by_id = {report.approach_id: report for report in critic_reports}

    max_cost = max((candidate.cost_estimate for candidate in candidates), default=0.0)
    verdicts = tuple(
        sorted(
            (
                score_candidate(
                    plan, candidate, critic_by_id[candidate.approach_id], max_cost=max_cost
                )
                for candidate in candidates
            ),
            key=lambda verdict: (-verdict.score, verdict.approach_id),
        )
    )

    best = verdicts[0]
    if best.eligible_for_accept:
        decision = PrototypeDecision(
            kind=DecisionKind.ACCEPT,
            reason="ac_coverage_and_evidence_satisfied",
            round_number=round_number,
            winner_approach_id=best.approach_id,
            verdicts=verdicts,
        )
    else:
        # Given review_candidate's invariant (a fully AC-covered, evidenced
        # candidate never carries a MISSING_EVIDENCE finding), "not eligible"
        # here always means either an unresolved critic finding or
        # incomplete AC coverage — never both false at once. A per-round
        # terminal REJECT ("this round is hopeless with zero budget left")
        # is a property of the bounded loop, not of a single round; see
        # :func:`run_bounded_revise` for the REJECT reasons
        # ``revise_stalled``/``revise_bounded_exhausted``.
        decision = PrototypeDecision(
            kind=DecisionKind.REVISE,
            reason="unresolved_findings_or_incomplete_ac_coverage",
            round_number=round_number,
            winner_approach_id=None,
            verdicts=verdicts,
        )

    return decision, critic_reports, diversity


@dataclass(frozen=True, slots=True)
class PrototypeGateReceipt:
    """Canonical, auditable receipt for a full (possibly multi-round) run."""

    plan: PrototypePlan
    rounds: tuple[PrototypeDecision, ...]
    final: PrototypeDecision
    stalled: bool

    @property
    def input_hash(self) -> str:
        return _fingerprint(self.plan.to_dict())

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": GATE_SCHEMA_VERSION,
            "input_hash": self.input_hash,
            "plan": self.plan.to_dict(),
            "rounds": [decision.to_dict() for decision in self.rounds],
            "final": self.final.to_dict(),
            "stalled": self.stalled,
        }

    @property
    def receipt_hash(self) -> str:
        return _fingerprint(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_hash": self.receipt_hash}


def run_bounded_revise(
    plan: PrototypePlan,
    judge: RoleIdentity,
    critic: RoleIdentity,
    rounds: Sequence[Sequence[PrototypeCandidate]],
    *,
    max_rounds: int = MAX_REVISE_ROUNDS,
) -> PrototypeGateReceipt:
    """Drive the bounded REVISE loop across caller-supplied candidate rounds.

    ``rounds`` is the sequence of candidate sets already produced for each
    revision pass (round 1, round 2, ...) — this contract does not itself
    call an LLM to generate a revision; it adjudicates whatever the caller
    supplies and enforces the bound + stall detection.

    Stops immediately on ACCEPT.  Stops on REJECT only when the leading
    score has stagnated (stall detection) or the round budget is exhausted;
    a bare REJECT with room left in the budget and an improving score is not
    treated as terminal — the caller is expected to keep revising.
    """

    if (
        not isinstance(max_rounds, int)
        or isinstance(max_rounds, bool)
        or max_rounds < 1
    ):
        raise ValueError("max_rounds must be a positive integer")
    if not rounds:
        raise ValueError("run_bounded_revise requires at least one round")
    if len(rounds) > max_rounds:
        raise ValueError(
            f"caller supplied more rounds ({len(rounds)}) than max_rounds={max_rounds}"
        )

    decisions: list[PrototypeDecision] = []
    previous_best_score: float | None = None
    stalled = False

    for index, candidates in enumerate(rounds, start=1):
        decision, _critic_reports, _diversity = decide_round(
            plan, candidates, judge, critic, round_number=index
        )
        decisions.append(decision)

        if decision.kind is DecisionKind.ACCEPT:
            return PrototypeGateReceipt(
                plan=plan, rounds=tuple(decisions), final=decision, stalled=False
            )

        current_best_score = decision.verdicts[0].score if decision.verdicts else None
        if (
            previous_best_score is not None
            and current_best_score is not None
            and (current_best_score - previous_best_score) <= STALL_EPSILON
        ):
            stalled = True
            stalled_decision = PrototypeDecision(
                kind=DecisionKind.REJECT,
                reason="revise_stalled",
                round_number=decision.round_number,
                winner_approach_id=None,
                verdicts=decision.verdicts,
            )
            decisions[-1] = stalled_decision
            return PrototypeGateReceipt(
                plan=plan,
                rounds=tuple(decisions),
                final=stalled_decision,
                stalled=True,
            )

        previous_best_score = current_best_score

        if index == max_rounds and index == len(rounds):
            # decide_round only ever returns ACCEPT (handled above, returns
            # early) or REVISE — never REJECT itself — so reaching the round
            # budget with a non-ACCEPT decision always means REVISE here;
            # the bounded loop converts that into an explicit REJECT with an
            # auditable "budget exhausted" reason instead of silently
            # returning a REVISE with nowhere left to go.
            exhausted = PrototypeDecision(
                kind=DecisionKind.REJECT,
                reason="revise_bounded_exhausted",
                round_number=decision.round_number,
                winner_approach_id=None,
                verdicts=decision.verdicts,
            )
            decisions[-1] = exhausted
            return PrototypeGateReceipt(
                plan=plan, rounds=tuple(decisions), final=exhausted, stalled=stalled
            )

    return PrototypeGateReceipt(
        plan=plan, rounds=tuple(decisions), final=decisions[-1], stalled=stalled
    )


def synthesize_candidates(
    candidates: Sequence[PrototypeCandidate],
    synthesizer: RoleIdentity,
) -> PrototypeCandidate:
    """Optionally combine ONLY mutually compatible candidates.

    Compatibility here is structural and conservative: candidates are
    compatible only when their declared scopes are pairwise disjoint (no two
    candidates claim to touch the same path).  Anything else raises —
    synthesis never silently papers over a real conflict.  The merged
    artifact is a brand-new candidate authored by the synthesizer and MUST
    be revalidated (:func:`review_candidate` + :func:`score_candidate`)
    exactly like any other candidate before it can be judged.
    """

    if synthesizer.role is not RoleKind.SYNTHESIZER:
        raise ValueError("synthesizer identity must declare role=synthesizer")
    ordered = sorted(candidates, key=lambda candidate: candidate.approach_id)
    if len(ordered) < 2:
        raise ValueError("synthesis requires at least 2 candidates")

    seen_scope: set[str] = set()
    for candidate in ordered:
        overlap = seen_scope & set(candidate.declared_scope)
        if overlap:
            raise ValueError(
                "candidates are not compatible for synthesis: overlapping scope "
                + ", ".join(sorted(overlap))
            )
        seen_scope.update(candidate.declared_scope)

    merged_tags: set[str] = set()
    merged_ops: set[str] = set()
    merged_claims: dict[str, Claim] = {}
    merged_ac: set[str] = set()
    merged_scope: set[str] = set()
    total_cost = 0.0
    max_risk = 0.0
    min_reversibility = 1.0
    for candidate in ordered:
        merged_tags.update(candidate.approach_tags)
        merged_ops.update(candidate.operations)
        for claim in candidate.claims:
            merged_claims[claim.claim_id] = claim
        merged_ac.update(candidate.ac_covered)
        merged_scope.update(candidate.declared_scope)
        total_cost += candidate.cost_estimate
        max_risk = max(max_risk, candidate.risk_estimate)
        min_reversibility = min(min_reversibility, candidate.reversibility)

    approach_id = "synthesis:" + "+".join(candidate.approach_id for candidate in ordered)
    return PrototypeCandidate(
        approach_id=approach_id,
        creator=synthesizer,
        approach_tags=tuple(sorted(merged_tags)),
        operations=tuple(sorted(merged_ops)),
        claims=tuple(
            sorted(merged_claims.values(), key=lambda claim: claim.claim_id)
        ),
        ac_covered=tuple(sorted(merged_ac)),
        declared_scope=tuple(sorted(merged_scope)),
        cost_estimate=total_cost,
        risk_estimate=max_risk,
        reversibility=min_reversibility,
    )


__all__ = [
    "CANDIDATE_SCHEMA_VERSION",
    "CRITIC_SCHEMA_VERSION",
    "DECISION_SCHEMA_VERSION",
    "DIVERSITY_WARNING_THRESHOLD",
    "FORBIDDEN_CAPABILITY_TOKENS",
    "GATE_SCHEMA_VERSION",
    "JUDGE_FINDING_PENALTY",
    "JUDGE_SCHEMA_VERSION",
    "JUDGE_WEIGHTS",
    "MAX_CANDIDATES",
    "MAX_REVISE_ROUNDS",
    "MIN_CANDIDATES",
    "PLAN_SCHEMA_VERSION",
    "STALL_EPSILON",
    "Claim",
    "CriticFinding",
    "CriticReport",
    "DecisionKind",
    "DefectClass",
    "DiversityPair",
    "DiversityReport",
    "ForbiddenCapabilityError",
    "JudgeVerdict",
    "PrototypeCandidate",
    "PrototypeDecision",
    "PrototypeGateReceipt",
    "PrototypePlan",
    "RoleIdentity",
    "RoleKind",
    "SelfJudgingError",
    "assert_no_self_judging",
    "decide_round",
    "measure_diversity",
    "review_candidate",
    "run_bounded_revise",
    "score_candidate",
    "synthesize_candidates",
]
