from agent.tool_invocation_pipeline import STAGES, ToolInvocation, ToolInvocationPipeline


def test_pipeline_runs_all_stages_in_order_and_emits_evidence():
    seen = []
    hooks = {}
    for stage in STAGES:
        def hook(value, *, _stage=stage, **kwargs):
            seen.append(_stage)
            return value
        hooks[stage] = hook

    pipeline = ToolInvocationPipeline(hooks=hooks)
    outcome = pipeline.run(
        ToolInvocation("demo", {"secret": "not stored"}, "call-1", "task-1"),
        lambda name, args: {"ok": True, "name": name},
    )

    assert outcome.status == "success"
    assert seen == [stage for stage in STAGES if stage != "execute"]
    assert outcome.trace == list(STAGES)
    assert outcome.evidence["tool_call_id"] == "call-1"
    assert "secret" not in str(outcome.evidence)


def test_pipeline_blocks_before_checkpoint_and_execution_but_persists_evidence():
    seen = []
    hooks = {
        "guardrail": lambda value, **kwargs: seen.append("guardrail") or False,
        "persist": lambda value, **kwargs: seen.append("persist") or value,
        "evidence": lambda value, **kwargs: seen.append("evidence") or value,
        "emit": lambda value, **kwargs: seen.append("emit") or value,
    }
    executed = []
    outcome = ToolInvocationPipeline(hooks=hooks).run(
        ToolInvocation("danger", {}, "call-2"),
        lambda name, args: executed.append(name),
    )

    assert outcome.status == "blocked"
    assert executed == []
    assert seen == ["guardrail", "persist", "evidence", "emit"]
    assert "checkpoint" not in outcome.trace


def test_pipeline_converts_execution_exception_to_classified_evidence():
    outcome = ToolInvocationPipeline().run(
        ToolInvocation("demo", {}),
        lambda name, args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert outcome.status == "error"
    assert outcome.error_type == "RuntimeError"
    assert outcome.trace[-4:] == ["persist", "evidence", "emit"] or outcome.trace[-4:] == ["result-classification", "persist", "evidence", "emit"]
