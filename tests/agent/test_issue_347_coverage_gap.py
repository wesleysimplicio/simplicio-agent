"""Issue #347 follow-up: close the widest coverage gaps in the two weakest
critical decision-path modules (`agent.goal_contract`,
`agent.tool_invocation_pipeline`) with deterministic, no-network tests.

Each test targets a specific missing line range identified by:

    python3 -m pytest tests/agent/test_issue_347_decision_paths.py \
        --cov=agent.goal_contract --cov=agent.tool_invocation_pipeline \
        --cov-report=term-missing -q

Tests follow the existing anti-tautology rule: each assertion exercises the
exact branch/value that would break if the corresponding code path were
reverted, not just a "runs without raising" smoke check.
"""

from __future__ import annotations

import pytest

from agent.goal_contract import (
    Evidence,
    Fact,
    GoalContract,
    GoalContractError,
    GoalState,
    Inference,
    OpenQuestion,
    VerificationRequiredError,
    WatcherRequirement,
)
from agent.tool_invocation_pipeline import (
    ToolDecision,
    ToolInvocation,
    ToolInvocationMetadata,
    ToolInvocationPipeline,
    default_tool_invocation_receipt_writer,
    pipeline_for_agent,
)


# ---------------------------------------------------------------------------
# agent.goal_contract — value object validation, properties, and dict round
# trips that the happy-path tests in test_issue_347_decision_paths.py never
# touch (lines 86-108, 131-169, 181-199, 213-243, 258-295).
# ---------------------------------------------------------------------------


def test_fact_statement_property_and_dict_round_trip_with_source() -> None:
    fact = Fact("db is healthy", source="probe://db", confidence=0.75)

    assert fact.statement == "db is healthy"
    as_dict = fact.to_dict()
    assert as_dict == {
        "text": "db is healthy",
        "source": "probe://db",
        "confidence": 0.75,
    }
    restored = Fact.from_dict(as_dict)
    assert restored == fact
    assert Fact.from_dict("bare string fact").text == "bare string fact"


def test_fact_rejects_empty_text_and_out_of_range_confidence() -> None:
    with pytest.raises(ValueError, match="fact text must be non-empty"):
        Fact("   ")
    with pytest.raises(ValueError, match="fact confidence must be between 0 and 1"):
        Fact("ok", confidence=1.5)
    with pytest.raises(ValueError, match="fact must be a string or object"):
        Fact.from_dict(123)


def test_inference_conclusion_property_dict_round_trip_and_basis_cleanup() -> None:
    inference = Inference(
        "service will fail over", basis=("evt-1", "  ", "evt-2"), confidence=0.6
    )

    assert inference.conclusion == "service will fail over"
    # Blank basis entries are dropped by __post_init__.
    assert inference.basis == ("evt-1", "evt-2")
    as_dict = inference.to_dict()
    assert as_dict == {
        "text": "service will fail over",
        "basis": ["evt-1", "evt-2"],
        "confidence": 0.6,
    }
    restored = Inference.from_dict(as_dict)
    assert restored == inference
    # from_dict accepts a single basis string, not just a list.
    single_basis = Inference.from_dict({"text": "x", "basis": "evt-solo"})
    assert single_basis.basis == ("evt-solo",)
    assert Inference.from_dict("bare inference").text == "bare inference"


def test_inference_rejects_empty_text_and_bad_confidence_and_type() -> None:
    with pytest.raises(ValueError, match="inference text must be non-empty"):
        Inference("")
    with pytest.raises(ValueError, match="inference confidence must be between 0 and 1"):
        Inference("ok", confidence=-0.1)
    with pytest.raises(ValueError, match="inference must be a string or object"):
        Inference.from_dict(42)


def test_open_question_property_dict_round_trip_and_validation() -> None:
    question = OpenQuestion("is the migration reversible?", blocking=True)

    assert question.question == "is the migration reversible?"
    assert question.to_dict() == {
        "text": "is the migration reversible?",
        "blocking": True,
    }
    restored = OpenQuestion.from_dict(question.to_dict())
    assert restored == question
    assert OpenQuestion.from_dict("bare question").text == "bare question"

    with pytest.raises(ValueError, match="open question text must be non-empty"):
        OpenQuestion("  ")
    with pytest.raises(ValueError, match="open question must be a string or object"):
        OpenQuestion.from_dict(7)


def test_evidence_ref_property_dict_round_trip_and_validation() -> None:
    evidence = Evidence(
        "receipt://issue-347/gap", kind="pytest", verified=False, watcher_id="w-1"
    )

    assert evidence.ref == "receipt://issue-347/gap"
    as_dict = evidence.to_dict()
    assert as_dict == {
        "reference": "receipt://issue-347/gap",
        "verified": False,
        "kind": "pytest",
        "watcher_id": "w-1",
    }
    restored = Evidence.from_dict(as_dict)
    assert restored == evidence
    assert Evidence.from_dict("bare-ref").reference == "bare-ref"

    with pytest.raises(ValueError, match="evidence reference must be non-empty"):
        Evidence("")
    with pytest.raises(ValueError, match="evidence must be a string or object"):
        Evidence.from_dict(3.14)


def test_watcher_requirement_properties_and_recomputed_false_blocks_satisfaction() -> None:
    watcher = WatcherRequirement("ci-green", required=True, satisfied=True)
    assert watcher.watcher == "ci-green"
    assert watcher.is_satisfied is True

    # satisfied=True but recomputed explicitly False must NOT count as
    # satisfied — this is the fail-closed "stale satisfaction" guard.
    stale = WatcherRequirement(
        "ci-green", required=True, satisfied=True, recomputed=False
    )
    assert stale.is_satisfied is False

    restored = WatcherRequirement.from_dict(watcher.to_dict())
    assert restored == watcher
    assert WatcherRequirement.from_dict("bare-watcher").name == "bare-watcher"

    with pytest.raises(ValueError, match="watcher name must be non-empty"):
        WatcherRequirement("")
    with pytest.raises(ValueError, match="watcher requirement must be a string or object"):
        WatcherRequirement.from_dict(True)


# ---------------------------------------------------------------------------
# agent.goal_contract — GoalContract convenience properties, add_* with
# already-built value objects, resume no-op, alias methods, and from_dict
# error handling (lines 380-460, 483-512, 592-605, 640-700).
# ---------------------------------------------------------------------------


def test_goal_contract_convenience_properties_expose_hashes_and_status() -> None:
    goal = GoalContract.create("ship the feature", ["tests pass", "docs updated"])

    assert goal.ac_hash == goal.acceptance_criteria_hash
    assert goal.objective_sha256 == goal.objective_hash
    assert goal.acceptance_criteria_sha256 == goal.acceptance_criteria_hash
    assert goal.evidence_refs == ()
    assert goal.watcher_requirements == goal.watchers
    assert goal.is_terminal is False
    assert goal.status == "active"
    assert goal.schema_version == "simplicio.goal-contract/v1"

    failed = goal.transition(GoalState.FAILED, reason="unrecoverable")
    assert failed.is_terminal is True
    assert failed.status == "failed"


def test_goal_contract_add_methods_accept_prebuilt_value_objects() -> None:
    goal = GoalContract.create("investigate outage")

    with_fact = goal.add_fact(Fact("latency spiked", source="dashboard"))
    with_inference = with_fact.add_inference(
        Inference("cache eviction storm", basis=("latency spiked",))
    )
    with_question = with_inference.add_open_question(
        OpenQuestion("root cause confirmed?", blocking=True)
    )

    assert with_fact.facts[0].text == "latency spiked"
    assert with_inference.inferences[0].text == "cache eviction storm"
    assert with_question.open_questions[0].blocking is True
    # Passing a prebuilt object must not double-wrap it.
    assert with_fact.facts[0] is not goal.facts
    assert isinstance(with_question.open_questions[0], OpenQuestion)


def test_goal_contract_resume_is_noop_when_already_active() -> None:
    goal = GoalContract.create("stay active")
    assert goal.resume() is goal


def test_goal_contract_complete_unverified_alias_and_transition() -> None:
    goal = GoalContract.create("best-effort task")
    unverified = goal.complete_unverified(reason="no watcher available")

    assert unverified.state is GoalState.COMPLETED_UNVERIFIED
    assert unverified.is_complete is True
    assert unverified.reason == "no watcher available"


def test_goal_contract_from_dict_rejects_non_mapping_and_bad_version() -> None:
    with pytest.raises(ValueError, match="goal contract must be an object"):
        GoalContract.from_dict("not-a-mapping")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unsupported schema_version"):
        GoalContract.from_dict(
            {
                "schema_version": "simplicio.goal-contract/v0",
                "objective": "x",
            }
        )


def test_goal_contract_from_dict_rejects_tampered_hashes() -> None:
    goal = GoalContract.create("tamper check", ["criterion-a"])
    payload = goal.to_dict()

    tampered_objective = dict(payload)
    tampered_objective["objective"] = "swapped objective"
    with pytest.raises(
        GoalContractError, match="objective hash does not match serialized objective"
    ):
        GoalContract.from_dict(tampered_objective)

    tampered_criteria = dict(payload)
    tampered_criteria["acceptance_criteria"] = ["swapped-criterion"]
    with pytest.raises(
        GoalContractError,
        match="acceptance criteria hash does not match serialized criteria",
    ):
        GoalContract.from_dict(tampered_criteria)


def test_goal_contract_objective_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="objective must be non-empty"):
        GoalContract(objective="   ")


def test_goal_contract_content_hash_changes_when_state_changes() -> None:
    goal = GoalContract.create("hash sensitivity check")
    paused = goal.transition(GoalState.PAUSED, reason="waiting")

    assert goal.content_hash() != paused.content_hash()
    assert goal.content_hash() == goal.content_hash()


def test_goal_contract_completed_verified_construction_requires_proof() -> None:
    with pytest.raises(VerificationRequiredError):
        GoalContract(objective="direct construction", state=GoalState.COMPLETED_VERIFIED)


# ---------------------------------------------------------------------------
# agent.tool_invocation_pipeline — checkpoint gating, exception paths in
# `run`/`complete`, decision coercion edge cases, and receipt-writer
# fail-safety (lines 208-320, 387-518, 664-717, 835-868).
# ---------------------------------------------------------------------------


def test_run_blocks_when_checkpoint_required_but_no_hook_registered() -> None:
    executed: list[str] = []
    pipeline = ToolInvocationPipeline()

    outcome = pipeline.run(
        ToolInvocation(
            "risky.tool",
            {},
            metadata=ToolInvocationMetadata(requires_checkpoint=True),
        ),
        lambda name, args: executed.append(name),
    )

    assert outcome.status == "blocked"
    assert outcome.invocation.metadata.blocked_by == "checkpoint"
    assert executed == []


def test_run_blocks_when_checkpoint_hook_denies() -> None:
    pipeline = ToolInvocationPipeline(
        hooks={"checkpoint": lambda value, *, attempt: False}
    )

    outcome = pipeline.run(
        ToolInvocation("gated.tool", {}), lambda name, args: "should-not-run"
    )

    assert outcome.status == "blocked"
    assert outcome.invocation.metadata.blocked_by == "checkpoint"
    assert outcome.evidence["checkpoint_ref"] == "checkpoint-denied"


def test_run_captures_executor_exception_and_persists_error_evidence() -> None:
    def boom(name: str, args: dict) -> None:
        raise RuntimeError("downstream failure")

    outcome = ToolInvocationPipeline().run(ToolInvocation("failing.tool", {}), boom)

    assert outcome.status == "error"
    assert outcome.error_type == "RuntimeError"
    assert outcome.evidence["error_message"] == "downstream failure"
    assert "persist" in outcome.trace
    assert "evidence" in outcome.trace


def test_complete_marks_blocked_when_required_checkpoint_missing_from_trace() -> None:
    invocation = ToolInvocation(
        "async.tool",
        {},
        metadata=ToolInvocationMetadata(requires_checkpoint=True),
    )
    pipeline = ToolInvocationPipeline()

    outcome = pipeline.complete(invocation, {"ok": True}, trace=["resolve", "normalize"])

    assert outcome.status == "blocked"
    assert outcome.invocation.metadata.blocked_by == "checkpoint"
    assert outcome.evidence["error_message"] == (
        "required checkpoint missing from invocation trace"
    )


def test_complete_is_idempotent_for_the_same_attempt_id() -> None:
    invocation = ToolInvocation(
        "async.tool",
        {"x": 1},
        "call-1",
        metadata=ToolInvocationMetadata(attempt_id="fixed-attempt-id"),
    )
    pipeline = ToolInvocationPipeline()

    first = pipeline.complete(invocation, {"ok": True}, trace=["execute"])
    second = pipeline.complete(invocation, {"ok": False}, trace=["execute"])

    # Second call must return the already-finalized outcome, not recompute.
    assert second.result == first.result == {"ok": True}


def test_decision_coercion_rejects_unrecognized_guardrail_value() -> None:
    # ``run`` wraps the whole front-half in a try/except, so a malformed
    # hook return value surfaces as a captured "error" outcome rather than
    # propagating — this pins that fail-safe behavior.
    pipeline = ToolInvocationPipeline(hooks={"guardrail": lambda value, *, attempt: 42})

    outcome = pipeline.run(ToolInvocation("bad.tool", {}), lambda name, args: None)

    assert outcome.status == "error"
    assert outcome.error_type == "TypeError"
    assert "guardrail must return a decision-like value" in outcome.evidence[
        "error_message"
    ]


def test_normalize_hook_returning_non_mapping_is_captured_as_error_outcome() -> None:
    pipeline = ToolInvocationPipeline(
        hooks={"normalize": lambda value, *, attempt: "not-a-mapping"}
    )

    outcome = pipeline.run(ToolInvocation("bad.tool", {}), lambda name, args: None)

    assert outcome.status == "error"
    assert outcome.error_type == "TypeError"
    assert "normalize must return a mapping" in outcome.evidence["error_message"]


def test_receipt_writer_failure_is_captured_in_evidence_and_marks_error() -> None:
    def failing_writer(receipt) -> None:
        raise OSError("ledger unavailable")

    outcome = ToolInvocationPipeline(receipt_writer=failing_writer).run(
        ToolInvocation("ledger.tool", {}), lambda name, args: "ok"
    )

    # The tool itself succeeded; the ledger write failure is what flips the
    # terminal status, and it must never be silently swallowed.
    assert outcome.status == "error"
    assert outcome.error_type == "OSError"
    assert outcome.evidence["receipt_error_type"] == "OSError"
    assert outcome.evidence["receipt_error_message"] == "ledger unavailable"


def test_pipeline_for_agent_wires_hooks_and_default_receipt_writer() -> None:
    class FakeAgent:
        session_id = "sess-1"
        tool_invocation_pipeline_hooks = {
            "classify": lambda value, *, attempt: "classified"
        }

    pipeline = pipeline_for_agent(FakeAgent(), "some.tool")

    assert pipeline.hooks["classify"](None, attempt=None) == "classified"
    assert pipeline.receipt_writer is default_tool_invocation_receipt_writer


def test_pipeline_for_agent_leaves_receipt_writer_none_without_session_id() -> None:
    class BareAgent:
        pass

    pipeline = pipeline_for_agent(BareAgent())

    assert pipeline.hooks == {}
    assert pipeline.receipt_writer is None


def test_default_tool_invocation_receipt_writer_persists_hashed_payload(monkeypatch) -> None:
    captured: dict = {}

    def fake_record_receipt(*, payload, yool_id, lane, status, meta):
        captured.update(
            payload=payload, yool_id=yool_id, lane=lane, status=status, meta=meta
        )
        return "receipt-handle"

    monkeypatch.setattr(
        "agent.telemetry.receipts.record_receipt", fake_record_receipt
    )

    outcome = ToolInvocationPipeline(
        receipt_writer=default_tool_invocation_receipt_writer
    ).run(ToolInvocation("ledger.tool", {"a": 1}), lambda name, args: {"b": 2})

    assert outcome.receipt is not None
    assert captured["yool_id"] == "tool-invocation:ledger.tool"
    assert captured["lane"] == "tool"
    assert captured["status"] == "success"
    assert captured["meta"]["receipt_id"] == outcome.receipt.receipt_id


def test_tool_decision_dataclass_defaults_to_allow() -> None:
    decision = ToolDecision()
    assert decision.allow is True
    assert decision.reason == ""
    assert dict(decision.detail) == {}
