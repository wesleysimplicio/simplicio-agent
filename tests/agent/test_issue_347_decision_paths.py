"""Deterministic issue #347 coverage across critical decision boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.autobiographical_memory import (
    AutobiographicalStore,
    CausalEvidence,
    EpisodeFact,
    EpisodeManifest,
    MemoryKind,
    MemoryScope,
)
from agent.autonomy_policy import (
    ActionRequest,
    ActionRisk,
    ApprovalGrant,
    AutonomyLevel,
    AutonomyPolicy,
    PolicyDecisionKind,
    PolicyReason,
)
from agent.belief_state import (
    BeliefDecision,
    BeliefFact,
    BeliefObservation,
    BeliefStateEngine,
    BeliefType,
    Freshness,
    SourceReliability,
)
from agent.goal_contract import Evidence, GoalContract, GoalState
from agent.tool_invocation_pipeline import (
    ToolInvocation,
    ToolInvocationMetadata,
    ToolInvocationPipeline,
)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "issue-347"
    / "decision_paths.json"
)


@pytest.fixture(scope="module")
def paths() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_planning_completion_requires_evidence_and_watcher(paths: dict) -> None:
    data = paths["planning"]
    goal = GoalContract.create(data["objective"], data["acceptance_criteria"])
    with pytest.raises(ValueError):
        goal.transition(GoalState.COMPLETED_VERIFIED)

    completed = (
        goal
        .add_evidence(Evidence(data["evidence"], kind="pytest"))
        .add_watcher(data["watcher"])
        .satisfy_watcher(data["watcher"], receipt="receipt://issue-347/watcher")
        .mark_completed_verified()
    )

    assert completed.is_complete
    assert completed.state is GoalState.COMPLETED_VERIFIED
    assert GoalContract.from_json(completed.to_json()) == completed


def test_memory_promotion_is_scoped_and_redacts_evidence(paths: dict) -> None:
    data = paths["memory"]
    fact = EpisodeFact(
        key=data["key"],
        summary=data["summary"],
        kind=MemoryKind.SEMANTIC,
        evidence=CausalEvidence(
            data["prediction_receipt"], data["outcome_receipt"], "prediction_observed"
        ),
        confidence=0.9,
        personal=True,
        user_preference=True,
        consent_receipt=data["consent_receipt"],
    )
    store = AutobiographicalStore()
    promoted = store.consolidate(
        EpisodeManifest(
            data["episode_id"], MemoryScope.USER_PROJECT, True, 10, (fact,)
        ),
        system_time=20,
    )

    assert len(promoted) == 1
    assert "alice@example.com" not in promoted[0].summary
    assert "secret-value" not in promoted[0].summary
    assert store.recall(data["key"], scope=MemoryScope.USER_PROJECT).known
    assert not store.recall(data["key"], scope=MemoryScope.RUNTIME_SELF).known


def test_tool_path_preserves_live_result_but_redacts_external_evidence(
    paths: dict,
) -> None:
    data = paths["tools"]
    outcome = ToolInvocationPipeline().run(
        ToolInvocation(
            data["name"],
            data["args"],
            data["tool_call_id"],
            metadata=ToolInvocationMetadata(external_result=True),
        ),
        lambda _name, _args: data["result"],
    )

    assert outcome.status == "success"
    assert outcome.result["secret"] == "keep-live"
    assert outcome.evidence["result"]["secret"] == "[REDACTED]"
    assert outcome.evidence["result"]["nested"]["token"] == "[REDACTED]"
    assert outcome.receipt is not None


def test_authority_matrix_is_deterministic_and_fail_closed(paths: dict) -> None:
    data = paths["authority"]
    for case in data["cases"]:
        policy = AutonomyPolicy(
            level=AutonomyLevel(case["level"]), policy_version=data["policy_version"]
        )
        action = ActionRequest(
            data["action_digest"],
            data["goal_hash"],
            data["scope"],
            ActionRisk(case["risk"]),
            case["mutating"],
        )
        decision = policy.decide(action, now_ns=data["now_ns"])
        assert decision.kind is PolicyDecisionKind(case["expected"])
        assert decision.reason is PolicyReason(case["reason"])

    payment = ActionRequest(
        data["action_digest"],
        data["goal_hash"],
        data["scope"],
        ActionRisk.PAYMENT,
        True,
    )
    approval = ApprovalGrant(
        data["action_digest"],
        data["goal_hash"],
        data["scope"],
        data["now_ns"] + 1,
        data["policy_version"],
    )
    allowed = AutonomyPolicy(
        level=AutonomyLevel.L3_GOAL_SCOPED, policy_version=data["policy_version"]
    ).decide(payment, now_ns=data["now_ns"], approval=approval)
    assert allowed.kind is PolicyDecisionKind.ALLOW
    assert allowed.reason is PolicyReason.APPROVAL_ACCEPTED


def test_belief_engine_covers_accept_clarify_block_and_defer(paths: dict) -> None:
    data = paths["belief"]
    engine = BeliefStateEngine(
        source_reliability={
            data["source"]: SourceReliability(
                data["source"], data["source_version"], data["reliability"]
            )
        }
    )
    for item in data["observations"].values():
        observation = BeliefObservation.from_dict({
            "subject": data["subject"],
            "source": data["source"],
            "source_event_id": item["source_event_id"],
            "value": item["value"],
            "freshness": item["freshness"],
            "confidence": item["confidence"],
        })
        assessment = engine.fuse((observation,))
        assert assessment.decision is BeliefDecision(item["expected"])

    deferred = engine.fuse(())
    assert deferred.decision is BeliefDecision.DEFER
    assert deferred.required_observation == "unknown"


def test_belief_engine_blocks_freshness_required_path(paths: dict) -> None:
    data = paths["belief"]
    item = data["observations"]["stale"]
    observation = BeliefObservation.from_dict({
        "subject": data["subject"],
        "source": data["source"],
        "source_event_id": item["source_event_id"],
        "value": item["value"],
        "freshness": Freshness.STALE.value,
        "confidence": item["confidence"],
    })
    assessment = BeliefStateEngine(
        source_reliability={
            data["source"]: SourceReliability(
                data["source"], data["source_version"], data["reliability"]
            )
        }
    ).fuse((observation,), require_fresh=True)

    assert assessment.decision is BeliefDecision.BLOCK
    assert assessment.reason == "stale observation"


def test_belief_observation_and_fact_round_trip_preserve_provenance() -> None:
    observation = BeliefObservation(
        subject="deployment.status",
        source="memory",
        source_event_id="evt-memory",
        distribution=(("ready", 0.8), ("blocked", 0.2)),
        belief_type=BeliefType.REMEMBERED,
        freshness=Freshness.UNKNOWN,
        evidence_handles=("receipt:b", "receipt:a", "receipt:a"),
        conflicts=("evt-old", "evt-old"),
        valid_time_ns=10,
        system_time_ns=20,
        expiry_ns=30,
    )
    restored = BeliefObservation.from_dict(observation.to_dict())
    fact = observation.to_fact(SourceReliability("memory", "v2", 0.9))
    restored_fact = BeliefFact.from_dict(fact.to_dict())

    assert restored == observation
    assert restored.content_hash() == observation.content_hash()
    assert restored_fact == fact
    assert len(fact.content_hash()) == 64
    assert observation.canonical_value().startswith('{"distribution"')


def test_belief_missing_and_default_source_paths_are_explicit() -> None:
    engine = BeliefStateEngine()
    missing = BeliefObservation(
        subject="deployment.status",
        source="unknown-sensor",
        source_event_id="evt-missing",
        missing=True,
    )
    assessment = engine.fuse((missing,))
    default = engine.reliability_for("unknown-sensor")
    profile = SourceReliability("known-sensor", "v1", 0.8)
    engine.register_source(profile)

    assert assessment.reason == "observation missing"
    assert assessment.missing == ("deployment.status",)
    assert default.version == "default"
    assert engine.reliability_for("known-sensor") is profile
    assert profile.to_dict()["reliability"] == 0.8

    with pytest.raises(ValueError):
        BeliefStateEngine(clarify_threshold=0.5, block_threshold=0.5)


def test_belief_conflicts_select_highest_confidence_and_request_clarification() -> None:
    engine = BeliefStateEngine(
        source_reliability={"sensor": SourceReliability("sensor", "v1", 1.0)}
    )
    observations = (
        BeliefObservation(
            "deployment.status", "sensor", "evt-ready", value="ready", confidence=0.9
        ),
        BeliefObservation(
            "deployment.status",
            "sensor",
            "evt-blocked",
            value="blocked",
            confidence=0.8,
        ),
    )

    assessment = engine.fuse(observations)

    assert assessment.decision is BeliefDecision.CLARIFY
    assert assessment.selected_fact is not None
    assert assessment.selected_fact.value == "ready"
    assert assessment.conflicts == ("deployment.status:evt-blocked",)
    assert assessment.evidence_to_change == ("evt-blocked",)


def test_planning_rejects_invalid_resume_and_missing_watcher(paths: dict) -> None:
    data = paths["planning"]
    goal = GoalContract.create(data["objective"], data["acceptance_criteria"])
    paused = goal.transition(GoalState.PAUSED, reason="waiting for CI")

    assert paused.resume().state is GoalState.ACTIVE
    assert goal.transition(GoalState.ACTIVE) is goal
    with pytest.raises(ValueError, match="invalid goal transition"):
        paused.transition(GoalState.COMPLETED_UNVERIFIED)

    with pytest.raises(KeyError, match="missing-watcher"):
        goal.satisfy_watcher("missing-watcher")


def test_memory_promotion_applies_per_fact_gates(paths: dict) -> None:
    data = paths["memory"]

    def fact(**changes: object) -> EpisodeFact:
        values: dict[str, object] = {
            "key": data["key"],
            "summary": "safe preference",
            "kind": MemoryKind.SEMANTIC,
            "evidence": CausalEvidence(
                data["prediction_receipt"],
                data["outcome_receipt"],
                "prediction_observed",
            ),
            "confidence": 0.9,
            "personal": False,
            "user_preference": False,
            "consent_receipt": data["consent_receipt"],
        }
        values.update(changes)
        return EpisodeFact(**values)  # type: ignore[arg-type]

    store = AutobiographicalStore()
    manifest = EpisodeManifest(
        "issue-347-gates",
        MemoryScope.USER_PROJECT,
        True,
        10,
        (
            fact(poisoned_source=True),
            fact(user_preference=True, consent_receipt=""),
            fact(summary="promoted"),
        ),
    )

    promoted = store.consolidate(manifest, system_time=20)

    assert tuple(memory.summary for memory in promoted) == ("promoted",)
    assert store.recall(data["key"], scope=MemoryScope.USER_PROJECT).known


def test_tool_action_gate_blocks_and_preserves_policy_reason(paths: dict) -> None:
    data = paths["tools"]
    executed: list[tuple[str, dict]] = []
    pipeline = ToolInvocationPipeline(
        hooks={
            "action-gate": lambda _value, *, attempt: {
                "allow": False,
                "reason": "approval required",
                "policy": "issue-347",
            }
        }
    )

    outcome = pipeline.run(
        ToolInvocation(data["name"], data["args"], data["tool_call_id"]),
        lambda name, args: executed.append((name, args)),
    )

    assert outcome.status == "blocked"
    assert outcome.invocation.metadata.blocked_by == "action-gate"
    assert outcome.evidence["error_message"] == "approval required"
    assert executed == []


def test_tool_hooks_normalize_decisions_and_persist_result() -> None:
    seen: list[tuple[str, object]] = []
    pipeline = ToolInvocationPipeline(
        redacted_result_keys=frozenset({"credential"}),
        hooks={
            "resolve": lambda value, *, attempt: f"{value}.resolved",
            "normalize": lambda value, *, attempt: {**value, "normalized": True},
            "authorize": lambda value, *, attempt: {**value, "authorized": True},
            "classify": lambda value, *, attempt: "issue-347",
            "guardrail": lambda value, *, attempt: True,
            "action-gate": lambda value, *, attempt: {"allow": True},
            "persist": lambda value, *, attempt: (
                seen.append(("persist", value)) or {"persisted": value}
            ),
        },
    )

    outcome = pipeline.run(
        ToolInvocation(
            "demo.tool",
            {"path": "README.md"},
            metadata=ToolInvocationMetadata(external_result=True),
        ),
        lambda name, args: {"credential": "live", "args": args},
    )

    assert outcome.status == "success"
    assert outcome.invocation.name == "demo.tool.resolved"
    assert outcome.invocation.args["normalized"] is True
    assert outcome.invocation.args["authorized"] is True
    assert outcome.result == {
        "persisted": {"credential": "live", "args": outcome.invocation.args}
    }
    assert outcome.evidence["result"]["persisted"]["credential"] == "[REDACTED]"
    assert seen and seen[0][0] == "persist"


def test_authority_level_and_policy_version_paths_are_explicit() -> None:
    action = ActionRequest(
        "sha256:issue-347",
        "sha256:goal",
        "workspace:issue-347",
        ActionRisk.PUBLISH,
        True,
    )
    assert (
        AutonomyPolicy(level=AutonomyLevel.L1_SUGGEST).decide(action, now_ns=1).reason
        is PolicyReason.SUPERVISION_REQUIRED
    )
    assert (
        AutonomyPolicy(level=AutonomyLevel.L4_PERSISTENT)
        .decide(action, now_ns=1)
        .reason
        is PolicyReason.HUMAN_GATE_REQUIRED
    )

    policy = AutonomyPolicy(
        level=AutonomyLevel.L3_GOAL_SCOPED, policy_version="issue-347/v2"
    )
    approval = ApprovalGrant(
        action.action_digest,
        action.goal_hash,
        action.scope,
        10,
        "issue-347/v1",
    )
    decision = policy.decide(action, now_ns=1, approval=approval)
    assert decision.reason is PolicyReason.HUMAN_GATE_REQUIRED
    assert decision.approval_used is False
    assert '"policy_version": "issue-347/v2"' in policy.to_json()


def test_belief_conflict_decisions_fail_closed_by_confidence() -> None:
    def assess(confidence: float) -> BeliefDecision:
        engine = BeliefStateEngine(
            source_reliability={"sensor": SourceReliability("sensor", "v1", 1.0)}
        )
        observations = (
            BeliefObservation(
                "deployment.status",
                "sensor",
                "evt-a",
                value="ready",
                confidence=confidence,
            ),
            BeliefObservation(
                "deployment.status",
                "sensor",
                "evt-b",
                value="blocked",
                confidence=0.1,
            ),
        )
        return engine.fuse(observations).decision

    assert assess(0.9) is BeliefDecision.CLARIFY
    assert assess(0.5) is BeliefDecision.DEFER
    assert assess(0.2) is BeliefDecision.BLOCK


def test_belief_stale_conflict_requires_freshness_or_clarification() -> None:
    observations = (
        BeliefObservation(
            "deployment.status",
            "sensor",
            "evt-stale-ready",
            value="ready",
            freshness=Freshness.STALE,
            confidence=0.9,
        ),
        BeliefObservation(
            "deployment.status",
            "sensor",
            "evt-stale-blocked",
            value="blocked",
            freshness=Freshness.STALE,
            confidence=0.8,
        ),
    )
    engine = BeliefStateEngine(
        source_reliability={"sensor": SourceReliability("sensor", "v1", 1.0)}
    )

    clarify = engine.fuse(observations)
    block = engine.fuse(observations, require_fresh=True)

    assert clarify.decision is BeliefDecision.CLARIFY
    assert clarify.reason == "stale conflicting observation"
    assert block.decision is BeliefDecision.BLOCK
    assert block.evidence_to_change == ("evt-stale-blocked",)
