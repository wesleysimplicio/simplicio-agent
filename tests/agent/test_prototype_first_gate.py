"""Tests for the Prototype-First Gate cognitive layer (issue #484, epic #568)."""

from __future__ import annotations

import json

import pytest

from agent.prototype_first_gate import (
    Claim,
    CriticReport,
    DecisionKind,
    DefectClass,
    DiversityReport,
    ForbiddenCapabilityError,
    JudgeVerdict,
    PrototypeCandidate,
    PrototypeGateReceipt,
    PrototypePlan,
    RoleIdentity,
    RoleKind,
    SelfJudgingError,
    assert_no_self_judging,
    decide_round,
    measure_diversity,
    review_candidate,
    run_bounded_revise,
    score_candidate,
    synthesize_candidates,
)


VERIFIED_EVIDENCE = frozenset(
    {
        "receipt:ac-1",
        "receipt:ac-2",
        "r",
        "r1",
        "r2",
    }
)

# Existing fixtures model real runtime receipts. Keep that explicit at the
# test boundary while retaining a direct handle for fail-closed tests.
_review_candidate = review_candidate
_decide_round = decide_round
_run_bounded_revise = run_bounded_revise


def review_candidate(*args: object, **kwargs: object) -> CriticReport:
    kwargs.setdefault("verified_evidence", VERIFIED_EVIDENCE)
    return _review_candidate(*args, **kwargs)  # type: ignore[arg-type]


def decide_round(*args: object, **kwargs: object) -> tuple[object, ...]:
    kwargs.setdefault("verified_evidence", VERIFIED_EVIDENCE)
    return _decide_round(*args, **kwargs)  # type: ignore[arg-type,return-value]


def run_bounded_revise(*args: object, **kwargs: object) -> PrototypeGateReceipt:
    kwargs.setdefault("verified_evidence", VERIFIED_EVIDENCE)
    return _run_bounded_revise(*args, **kwargs)  # type: ignore[arg-type]


def planner_identity(identity: str = "planner-1") -> RoleIdentity:
    return RoleIdentity(identity=identity, role=RoleKind.PLANNER, capabilities=("plan",))


def creator_identity(identity: str) -> RoleIdentity:
    return RoleIdentity(identity=identity, role=RoleKind.CREATOR, capabilities=("draft",))


def critic_identity(identity: str = "critic-1") -> RoleIdentity:
    return RoleIdentity(identity=identity, role=RoleKind.CRITIC, capabilities=("review",))


def judge_identity(identity: str = "judge-1") -> RoleIdentity:
    return RoleIdentity(identity=identity, role=RoleKind.JUDGE, capabilities=("score",))


def synthesizer_identity(identity: str = "synth-1") -> RoleIdentity:
    return RoleIdentity(
        identity=identity, role=RoleKind.SYNTHESIZER, capabilities=("combine",)
    )


def make_plan(**overrides: object) -> PrototypePlan:
    values: dict[str, object] = {
        "hypothesis": "A cache-first approach reduces latency for repeat reads.",
        "level": "spike",
        "candidate_types": ("cache", "no-cache"),
        "budgets": {"tokens": 5000, "time_s": 60},
        "validators": ("pytest",),
        "acceptance_criteria": ("ac-1", "ac-2"),
        "planner": planner_identity(),
        "allowed_scope": ("lib/cache/",),
    }
    values.update(overrides)
    return PrototypePlan(**values)  # type: ignore[arg-type]


def make_candidate(approach_id: str, **overrides: object) -> PrototypeCandidate:
    values: dict[str, object] = {
        "approach_id": approach_id,
        "creator": creator_identity(f"creator-{approach_id}"),
        "approach_tags": ("cache", "lru"),
        "operations": ("read", "write"),
        "claims": (
            Claim("ac-1", "covers ac-1", ("receipt:ac-1",)),
            Claim("ac-2", "covers ac-2", ("receipt:ac-2",)),
        ),
        "ac_covered": ("ac-1", "ac-2"),
        "declared_scope": ("lib/cache/store.py",),
        "cost_estimate": 10.0,
        "risk_estimate": 0.1,
        "reversibility": 0.9,
    }
    values.update(overrides)
    return PrototypeCandidate(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Role identity / capability allowlist — no delivery authority anywhere.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "capability",
    [
        "promote",
        "deliver_to_prod",
        "publish_release",
        "merge_main",
        "write_to_target",
        "deploy_service",
        "push_to_prod",
    ],
)
def test_forbidden_delivery_capability_rejected_for_every_role(capability: str) -> None:
    for role in RoleKind:
        with pytest.raises(ForbiddenCapabilityError):
            RoleIdentity(identity="x", role=role, capabilities=(capability,))


def test_role_identity_allows_ordinary_capabilities() -> None:
    identity = RoleIdentity(
        identity="creator-a", role=RoleKind.CREATOR, capabilities=("draft", "read_repo")
    )
    assert identity.capabilities == ("draft", "read_repo")


def test_plan_requires_planner_role() -> None:
    not_a_planner = creator_identity("not-planner")
    with pytest.raises(ValueError, match="role=planner"):
        make_plan(planner=not_a_planner)


def test_candidate_requires_creator_role() -> None:
    with pytest.raises(ValueError, match="role=creator"):
        make_candidate("a", creator=critic_identity())


# ---------------------------------------------------------------------------
# Diversity is measured, not assumed.
# ---------------------------------------------------------------------------


def test_near_identical_candidates_register_low_diversity_warning() -> None:
    a = make_candidate("a")
    b = make_candidate("b")  # same tags/operations as "a" — near-identical approach

    report = measure_diversity((a, b))

    assert isinstance(report, DiversityReport)
    assert report.mean_distance == pytest.approx(0.0)
    assert report.warning is True
    assert report.low_diversity_pairs == ("a:b",)


def test_genuinely_different_candidates_register_higher_diversity() -> None:
    a = make_candidate("a", approach_tags=("cache", "lru"), operations=("read", "write"))
    b = make_candidate(
        "b",
        approach_tags=("no-cache", "streaming"),
        operations=("stream", "chunk"),
    )

    report = measure_diversity((a, b))

    assert report.mean_distance == pytest.approx(1.0)
    assert report.warning is False
    assert report.low_diversity_pairs == ()


def test_measure_diversity_is_order_independent() -> None:
    a = make_candidate("a", approach_tags=("cache",), operations=("read",))
    b = make_candidate("b", approach_tags=("stream",), operations=("chunk",))

    forward = measure_diversity((a, b))
    backward = measure_diversity((b, a))

    assert forward.mean_distance == backward.mean_distance
    assert forward.pairs[0].distance == backward.pairs[0].distance


def test_measure_diversity_enforces_bounds() -> None:
    with pytest.raises(ValueError, match="at least"):
        measure_diversity((make_candidate("solo"),))


# ---------------------------------------------------------------------------
# Critic reliably finds injected defects.
# ---------------------------------------------------------------------------


def test_critic_finds_missing_evidence_defect() -> None:
    plan = make_plan()
    candidate = make_candidate(
        "a",
        claims=(Claim("ac-1", "covers ac-1", ("receipt:ac-1",)),),
        ac_covered=("ac-1", "ac-2"),  # claims ac-2 covered but has no matching claim
    )

    report = review_candidate(
        plan, candidate, critic_identity(), verified_evidence=VERIFIED_EVIDENCE
    )

    assert isinstance(report, CriticReport)
    assert not report.clean
    classes = {finding.defect_class for finding in report.findings}
    assert DefectClass.MISSING_EVIDENCE in classes
    missing = [f for f in report.findings if f.defect_class is DefectClass.MISSING_EVIDENCE]
    assert any(f.related_id == "ac-2" for f in missing)


def test_critic_finds_unfounded_claim_defect() -> None:
    plan = make_plan()
    candidate = make_candidate(
        "a",
        claims=(
            Claim("ac-1", "covers ac-1", ("receipt:ac-1",)),
            Claim("ac-2", "covers ac-2", ()),  # no evidence handles at all
        ),
    )

    report = review_candidate(
        plan, candidate, critic_identity(), verified_evidence=VERIFIED_EVIDENCE
    )

    classes = {finding.defect_class for finding in report.findings}
    assert DefectClass.UNFOUNDED_CLAIM in classes


def test_critic_finds_scope_drift_defect() -> None:
    plan = make_plan(allowed_scope=("lib/cache/",))
    candidate = make_candidate("a", declared_scope=("lib/cache/store.py", "lib/other/leak.py"))

    report = review_candidate(
        plan, candidate, critic_identity(), verified_evidence=VERIFIED_EVIDENCE
    )

    drift = [f for f in report.findings if f.defect_class is DefectClass.SCOPE_DRIFT]
    assert len(drift) == 1
    assert drift[0].related_id == "lib/other/leak.py"


def test_critic_reports_clean_for_well_formed_candidate() -> None:
    plan = make_plan()
    candidate = make_candidate("a")

    report = review_candidate(
        plan, candidate, critic_identity(), verified_evidence=VERIFIED_EVIDENCE
    )

    assert report.clean
    assert report.findings == ()


def test_critic_blocks_unverified_handles_by_default() -> None:
    plan = make_plan()
    candidate = make_candidate("a")

    # No runtime receipt index means no evidence is available to this gate.
    report = _review_candidate(plan, candidate, critic_identity())

    assert not report.clean
    assert report.verified_evidence_handles == ()
    assert any(
        finding.detail == "evidence handle is unavailable or unverified"
        for finding in report.findings
    )

    decision, _reports, _diversity = _decide_round(
        plan,
        (candidate, make_candidate("b", approach_tags=("stream",))),
        judge_identity(),
        critic_identity(),
        round_number=1,
    )
    assert decision.kind is DecisionKind.REVISE


def test_receipt_preserves_critic_diversity_and_judge_audit() -> None:
    plan = make_plan()
    receipt = run_bounded_revise(
        plan,
        judge_identity(),
        critic_identity(),
        [(make_candidate("good"), make_candidate("also-good"))],
    )

    assert len(receipt.critic_reports) == 1
    assert len(receipt.critic_reports[0]) == 2
    assert len(receipt.diversity_reports) == 1
    assert receipt.final.judge.identity == "judge-1"
    payload = receipt.to_dict()
    assert payload["critic_reports"][0][0]["schema_version"] == "simplicio.prototype-critic/v1"
    assert payload["diversity_reports"][0]["pairs"]
    assert payload["final"]["judge"]["role"] == "judge"


def test_critic_requires_critic_role() -> None:
    plan = make_plan()
    candidate = make_candidate("a")
    with pytest.raises(ValueError, match="role=critic"):
        review_candidate(
            plan, candidate, judge_identity(), verified_evidence=VERIFIED_EVIDENCE
        )


# ---------------------------------------------------------------------------
# Self-judging is hard-blocked.
# ---------------------------------------------------------------------------


def test_self_judging_is_hard_blocked() -> None:
    creator = creator_identity("same-identity")
    candidate = make_candidate("a", creator=creator)
    judge_with_same_identity = RoleIdentity(
        identity="same-identity", role=RoleKind.JUDGE, capabilities=("score",)
    )

    with pytest.raises(SelfJudgingError):
        assert_no_self_judging(judge_with_same_identity, (candidate,))


def test_self_judging_blocks_the_whole_round_decision() -> None:
    creator = creator_identity("same-identity")
    a = make_candidate("a", creator=creator)
    b = make_candidate("b", approach_tags=("stream",), operations=("chunk",))
    plan = make_plan()
    self_judge = RoleIdentity(
        identity="same-identity", role=RoleKind.JUDGE, capabilities=("score",)
    )

    with pytest.raises(SelfJudgingError):
        decide_round(
            plan,
            (a, b),
            self_judge,
            critic_identity(),
            round_number=1,
            verified_evidence=VERIFIED_EVIDENCE,
        )


def test_independent_judge_with_distinct_identity_is_allowed() -> None:
    creator = creator_identity("creator-only")
    candidate = make_candidate("a", creator=creator)
    judge = judge_identity("independent-judge")

    assert_no_self_judging(judge, (candidate,))  # does not raise


def test_judge_requires_judge_role() -> None:
    with pytest.raises(ValueError, match="role=judge"):
        assert_no_self_judging(creator_identity("not-a-judge"), (make_candidate("a"),))


# ---------------------------------------------------------------------------
# Judge scoring and ACCEPT gating (AC coverage + evidence, not plausibility).
# ---------------------------------------------------------------------------


def test_score_candidate_is_explainable_and_deterministic() -> None:
    plan = make_plan()
    candidate = make_candidate("a")
    critic_report = review_candidate(
        plan, candidate, critic_identity(), verified_evidence=VERIFIED_EVIDENCE
    )

    verdict = score_candidate(plan, candidate, critic_report, max_cost=10.0)

    assert isinstance(verdict, JudgeVerdict)
    assert verdict.ac_coverage_ratio == pytest.approx(1.0)
    assert verdict.evidence_present is True
    assert verdict.critic_finding_count == 0
    assert verdict.eligible_for_accept is True
    assert set(verdict.breakdown) == {
        "ac_coverage",
        "evidence",
        "cost",
        "risk",
        "reversibility",
        "critic_penalty",
    }
    assert verdict.score == pytest.approx(sum(verdict.breakdown.values()))


def test_high_score_alone_does_not_grant_accept_without_evidence() -> None:
    plan = make_plan()
    # No claims at all -> "looks plausible" (cheap, low risk, reversible) but
    # zero evidence and zero AC coverage. Must not be eligible for ACCEPT.
    candidate = make_candidate(
        "a",
        claims=(),
        ac_covered=(),
        cost_estimate=0.0,
        risk_estimate=0.0,
        reversibility=1.0,
    )
    critic_report = review_candidate(
        plan, candidate, critic_identity(), verified_evidence=VERIFIED_EVIDENCE
    )

    verdict = score_candidate(plan, candidate, critic_report, max_cost=10.0)

    assert verdict.evidence_present is False
    assert verdict.ac_coverage_ratio == pytest.approx(0.0)
    assert verdict.eligible_for_accept is False


def test_decide_round_accepts_only_when_bar_is_met() -> None:
    plan = make_plan()
    good = make_candidate("good")
    weak = make_candidate(
        "weak",
        approach_tags=("stream",),
        operations=("chunk",),
        claims=(),
        ac_covered=(),
    )

    decision, critic_reports, diversity = decide_round(
        plan, (good, weak), judge_identity(), critic_identity(), round_number=1
    )

    assert decision.kind is DecisionKind.ACCEPT
    assert decision.winner_approach_id == "good"
    assert len(critic_reports) == 2
    assert isinstance(diversity, DiversityReport)


def test_decide_round_revises_when_no_candidate_meets_the_bar() -> None:
    plan = make_plan()
    a = make_candidate("a", claims=(), ac_covered=())
    b = make_candidate(
        "b",
        approach_tags=("stream",),
        operations=("chunk",),
        claims=(),
        ac_covered=(),
    )

    decision, _critic_reports, _diversity = decide_round(
        plan, (a, b), judge_identity(), critic_identity(), round_number=1
    )

    assert decision.kind in (DecisionKind.REVISE, DecisionKind.REJECT)
    assert decision.winner_approach_id is None


def test_reject_records_a_reason() -> None:
    plan = make_plan()
    a = make_candidate(
        "a",
        claims=(Claim("ac-1", "covers ac-1", ("r1",)),),
        ac_covered=("ac-1",),  # missing ac-2 -> incomplete but critic-clean
    )
    b = make_candidate(
        "b",
        approach_tags=("stream",),
        operations=("chunk",),
        claims=(Claim("ac-1", "covers ac-1", ("r2",)),),
        ac_covered=("ac-1",),
    )

    decision, _reports, _diversity = decide_round(
        plan, (a, b), judge_identity(), critic_identity(), round_number=1
    )

    assert decision.reason
    assert decision.kind is not DecisionKind.ACCEPT


# ---------------------------------------------------------------------------
# Bounded REVISE loop + stall detection.
# ---------------------------------------------------------------------------


def _incomplete_round(
    tag: str, *, risk: float = 0.1
) -> tuple[PrototypeCandidate, ...]:
    # risk_estimate feeds an absolute (not round-relative) score component,
    # so varying it across rounds is what actually moves the leading score
    # — cost_estimate is normalized *within* a round and so cannot express
    # a genuine cross-round improvement on its own.
    a = make_candidate(
        f"a-{tag}",
        claims=(Claim("ac-1", "x", ("r",)),),
        ac_covered=("ac-1",),
        risk_estimate=risk,
    )
    b = make_candidate(
        f"b-{tag}",
        approach_tags=("stream",),
        operations=("chunk",),
        claims=(Claim("ac-1", "x", ("r",)),),
        ac_covered=("ac-1",),
        risk_estimate=risk,
    )
    return (a, b)


def test_bounded_revise_stalls_when_score_does_not_improve() -> None:
    plan = make_plan()
    # Identical candidate shape each round -> identical best score -> stall.
    rounds = [_incomplete_round("r1"), _incomplete_round("r2")]

    receipt = run_bounded_revise(plan, judge_identity(), critic_identity(), rounds)

    assert isinstance(receipt, PrototypeGateReceipt)
    assert receipt.stalled is True
    assert receipt.final.kind is DecisionKind.REJECT
    assert receipt.final.reason == "revise_stalled"
    assert len(receipt.rounds) == 2


def test_bounded_revise_stops_at_max_rounds_with_reject() -> None:
    plan = make_plan()
    # Vary risk each round so the leading score actually keeps improving
    # (lower risk -> higher score) and stall detection does NOT fire early
    # — this isolates the max-rounds exhaustion path from the stall path.
    rounds = [
        _incomplete_round("1", risk=0.5),
        _incomplete_round("2", risk=0.3),
        _incomplete_round("3", risk=0.1),
    ]

    receipt = run_bounded_revise(
        plan, judge_identity(), critic_identity(), rounds, max_rounds=3
    )

    assert len(receipt.rounds) == 3
    assert receipt.final.kind is DecisionKind.REJECT
    assert receipt.final.reason == "revise_bounded_exhausted"
    assert receipt.stalled is False


def test_bounded_revise_accepts_as_soon_as_a_round_clears_the_bar() -> None:
    plan = make_plan()
    incomplete = _incomplete_round("1")
    complete = (make_candidate("good"), make_candidate("also-good"))
    rounds = [incomplete, complete]

    receipt = run_bounded_revise(plan, judge_identity(), critic_identity(), rounds)

    assert receipt.final.kind is DecisionKind.ACCEPT
    assert len(receipt.rounds) == 2
    assert receipt.stalled is False


def test_run_bounded_revise_rejects_more_rounds_than_max() -> None:
    plan = make_plan()
    rounds = [_incomplete_round("1"), _incomplete_round("2")]
    with pytest.raises(ValueError, match="max_rounds"):
        run_bounded_revise(plan, judge_identity(), critic_identity(), rounds, max_rounds=1)


def test_run_bounded_revise_requires_at_least_one_round() -> None:
    plan = make_plan()
    with pytest.raises(ValueError, match="at least one round"):
        run_bounded_revise(plan, judge_identity(), critic_identity(), [])


# ---------------------------------------------------------------------------
# Receipt determinism / crash-retry safety (pure functions => safe to retry).
# ---------------------------------------------------------------------------


def test_receipt_is_deterministic_and_json_serializable() -> None:
    plan = make_plan()
    rounds = [(make_candidate("good"), make_candidate("also-good"))]

    receipt_a = run_bounded_revise(plan, judge_identity(), critic_identity(), rounds)
    receipt_b = run_bounded_revise(plan, judge_identity(), critic_identity(), rounds)

    assert receipt_a.receipt_hash == receipt_b.receipt_hash
    payload = receipt_a.to_dict()
    json.dumps(payload, sort_keys=True)
    assert len(payload["receipt_hash"]) == 64


def test_crash_mid_pipeline_then_retry_succeeds_identically() -> None:
    """Simulate a crash inside critic review; retrying with the same inputs
    (the pure-function contract) must reproduce the exact same decision —
    no partial/mutated state leaks between attempts."""

    plan = make_plan()
    candidates = (make_candidate("good"), make_candidate("also-good"))

    call_count = {"n": 0}
    real_review = review_candidate

    def flaky_review(plan_arg, candidate_arg, critic_arg, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated mid-pipeline crash")
        return real_review(plan_arg, candidate_arg, critic_arg, **kwargs)

    import agent.prototype_first_gate as gate_module

    original = gate_module.review_candidate
    gate_module.review_candidate = flaky_review
    try:
        with pytest.raises(RuntimeError, match="simulated mid-pipeline crash"):
            decide_round(
                plan, candidates, judge_identity(), critic_identity(), round_number=1
            )
    finally:
        gate_module.review_candidate = original

    # Retry with the same inputs after "recovering" — must succeed and be
    # identical to a clean run, proving there is no leaked partial state.
    decision, _reports, _diversity = decide_round(
        plan, candidates, judge_identity(), critic_identity(), round_number=1
    )
    decision_replay, _reports2, _diversity2 = decide_round(
        plan, candidates, judge_identity(), critic_identity(), round_number=1
    )
    assert decision.to_dict() == decision_replay.to_dict()
    assert decision.kind is DecisionKind.ACCEPT


# ---------------------------------------------------------------------------
# Synthesizer: optional, compatible-only, forces revalidation.
# ---------------------------------------------------------------------------


def test_synthesize_merges_only_disjoint_scope_candidates() -> None:
    a = make_candidate("a", declared_scope=("lib/cache/store.py",))
    b = make_candidate(
        "b",
        approach_tags=("stream",),
        operations=("chunk",),
        declared_scope=("lib/stream/reader.py",),
    )

    merged = synthesize_candidates((a, b), synthesizer_identity())

    assert merged.creator.role is RoleKind.SYNTHESIZER
    assert set(merged.declared_scope) == {"lib/cache/store.py", "lib/stream/reader.py"}
    assert set(merged.ac_covered) == {"ac-1", "ac-2"}

    # The merged artifact must be revalidated like any other candidate.
    plan = make_plan(allowed_scope=("lib/cache/", "lib/stream/"))
    report = review_candidate(plan, merged, critic_identity())
    assert report.clean


def test_synthesize_rejects_overlapping_scope_candidates() -> None:
    a = make_candidate("a", declared_scope=("lib/cache/store.py",))
    b = make_candidate("b", declared_scope=("lib/cache/store.py",))

    with pytest.raises(ValueError, match="not compatible"):
        synthesize_candidates((a, b), synthesizer_identity())


def test_synthesize_requires_synthesizer_role() -> None:
    a = make_candidate("a")
    b = make_candidate("b", approach_tags=("stream",), operations=("chunk",))
    with pytest.raises(ValueError, match="role=synthesizer"):
        synthesize_candidates((a, b), judge_identity())


def test_synthesize_requires_at_least_two_candidates() -> None:
    with pytest.raises(ValueError, match="at least 2 candidates"):
        synthesize_candidates((make_candidate("solo"),), synthesizer_identity())


# ---------------------------------------------------------------------------
# Plan / role validation edge cases.
# ---------------------------------------------------------------------------


def test_role_identity_rejects_bad_lane() -> None:
    with pytest.raises(ValueError, match="lane must be one of"):
        RoleIdentity(identity="x", role=RoleKind.CREATOR, lane="urgent")


def test_role_identity_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RoleIdentity(identity="  ", role=RoleKind.CREATOR)


def test_role_identity_coerces_plain_string_role() -> None:
    identity = RoleIdentity(identity="x", role="creator")
    assert identity.role is RoleKind.CREATOR


@pytest.mark.parametrize("bad_level", ["", "unknown-level", "  "])
def test_plan_rejects_invalid_level(bad_level: str) -> None:
    with pytest.raises(ValueError):
        make_plan(level=bad_level)


def test_plan_rejects_empty_candidate_types() -> None:
    with pytest.raises(ValueError, match="candidate_types"):
        make_plan(candidate_types=())


def test_plan_rejects_negative_budget() -> None:
    with pytest.raises(ValueError, match="budgets"):
        make_plan(budgets={"tokens": -1})


def test_plan_rejects_empty_acceptance_criteria() -> None:
    with pytest.raises(ValueError, match="acceptance_criteria"):
        make_plan(acceptance_criteria=())


def test_plan_to_dict_round_trips_schema_fields() -> None:
    plan = make_plan()
    payload = plan.to_dict()
    assert payload["schema_version"] == "simplicio.prototype-plan/v1"
    assert payload["planner"]["role"] == "planner"


def test_candidate_rejects_duplicate_claim_ids() -> None:
    with pytest.raises(ValueError, match="claim_id values must be unique"):
        make_candidate(
            "a",
            claims=(
                Claim("dup", "one", ("r1",)),
                Claim("dup", "two", ("r2",)),
            ),
        )


def test_candidate_rejects_empty_approach_tags() -> None:
    with pytest.raises(ValueError, match="approach_tags"):
        make_candidate("a", approach_tags=())


def test_candidate_rejects_negative_cost() -> None:
    with pytest.raises(ValueError, match="cost_estimate"):
        make_candidate("a", cost_estimate=-1.0)


@pytest.mark.parametrize("bad_value", [-0.1, 1.1])
def test_candidate_rejects_out_of_range_risk_and_reversibility(bad_value: float) -> None:
    with pytest.raises(ValueError):
        make_candidate("a", risk_estimate=bad_value)
    with pytest.raises(ValueError):
        make_candidate("a", reversibility=bad_value)


def test_measure_diversity_enforces_upper_bound() -> None:
    too_many = tuple(
        make_candidate(f"c{i}", approach_tags=(f"tag{i}",), operations=(f"op{i}",))
        for i in range(9)
    )
    with pytest.raises(ValueError, match="MAX_CANDIDATES"):
        measure_diversity(too_many)


def test_decide_round_revises_when_candidates_declare_no_ac_coverage() -> None:
    # Neither candidate claims to cover any AC at all (no MISSING_EVIDENCE
    # finding fires, since nothing was claimed) — ac_coverage_ratio is still
    # 0.0, so the round must REVISE rather than ACCEPT on a "clean but
    # empty" candidate.
    plan = make_plan()
    a = make_candidate("a", claims=(), ac_covered=())
    b = make_candidate(
        "b", approach_tags=("stream",), operations=("chunk",), claims=(), ac_covered=()
    )
    decision, critic_reports, _diversity = decide_round(
        plan, (a, b), judge_identity(), critic_identity(), round_number=1
    )
    assert decision.kind is DecisionKind.REVISE
    assert all(report.clean for report in critic_reports)


def test_gate_receipt_input_hash_matches_plan_fingerprint() -> None:
    plan = make_plan()
    rounds = [(make_candidate("good"), make_candidate("also-good"))]
    receipt = run_bounded_revise(plan, judge_identity(), critic_identity(), rounds)
    assert len(receipt.input_hash) == 64


def test_component_to_dict_methods_serialize_cleanly() -> None:
    plan = make_plan()
    candidate = make_candidate("a")
    critic_report = review_candidate(plan, candidate, critic_identity())
    diversity = measure_diversity((candidate, make_candidate("b", approach_tags=("s",), operations=("o",))))

    payload = {
        "claim": candidate.claims[0].to_dict(),
        "candidate": candidate.to_dict(),
        "critic_report": critic_report.to_dict(),
        "diversity_pair": diversity.pairs[0].to_dict(),
        "diversity_report": diversity.to_dict(),
    }
    json.dumps(payload, sort_keys=True)
    assert payload["claim"]["claim_id"] in ("ac-1", "ac-2")
    assert payload["candidate"]["schema_version"] == "simplicio.prototype-candidate/v1"
    assert payload["critic_report"]["schema_version"] == "simplicio.prototype-critic/v1"


def test_jaccard_distance_of_two_empty_feature_sets_is_zero() -> None:
    a = make_candidate("a", approach_tags=("shared",), operations=())
    b = make_candidate("b", approach_tags=("shared",), operations=())
    report = measure_diversity((a, b))
    assert report.pairs[0].distance == pytest.approx(0.0)
