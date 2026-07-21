import json
from types import SimpleNamespace
from pathlib import Path

from agent.tool_invocation_pipeline import (
    STAGES,
    SerialToolExecutorAdapter,
    ToolDecision,
    ToolInvocation,
    ToolInvocationMetadata,
    ToolInvocationPipeline,
    default_tool_invocation_receipt_writer,
    pipeline_for_agent,
)
from tools.watcher_gate import Verdict, watch_result_boundary


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tool-pipeline"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_pipeline_runs_required_stages_and_serial_adapter_in_order():
    seen = []
    hooks = {
        stage: (lambda value, *, attempt, _stage=stage: seen.append(_stage) or value)
        for stage in STAGES
        if stage != "execute"
    }
    pipeline = ToolInvocationPipeline(hooks=hooks)
    adapter = SerialToolExecutorAdapter(
        execute_fn=lambda name, args: {"ok": True, "name": name, "args": args}
    )

    outcome = pipeline.run(
        ToolInvocation(**_fixture("invocation.json")),
        adapter,
    )

    assert outcome.status == "success"
    assert seen == [stage for stage in STAGES if stage != "execute"]
    assert outcome.trace == list(STAGES)
    assert adapter.executed_attempt_ids == [outcome.invocation.metadata.attempt_id]
    assert outcome.evidence["tool"] == "demo.tool"
    assert outcome.receipt is not None


def test_pipeline_blocks_before_checkpoint_and_execute_but_still_persists_receipt():
    persisted = []
    receipts = []
    pipeline = ToolInvocationPipeline(
        hooks={
            "guardrail": lambda value, *, attempt: ToolDecision(
                allow=False,
                reason="dangerous",
                detail={"policy": "readonly"},
            ),
            "persist": lambda value, *, attempt: (
                persisted.append(attempt.status) or value
            ),
        },
        receipt_writer=receipts.append,
    )
    executed = []

    outcome = pipeline.run(
        ToolInvocation("danger.tool", {"path": "README.md"}, "call-2"),
        lambda name, args: executed.append((name, args)),
    )

    assert outcome.status == "blocked"
    assert executed == []
    assert "checkpoint" not in outcome.trace
    assert "execute" not in outcome.trace
    assert persisted == ["blocked"]
    assert len(receipts) == 1
    assert receipts[0].blocked_by == "guardrail"


def test_pipeline_checkpoint_gate_fails_closed_before_execution():
    executed = []
    outcome = ToolInvocationPipeline(
        hooks={"checkpoint": lambda value, *, attempt: False}
    ).run(
        ToolInvocation(
            "write_file",
            {"path": "README.md"},
            metadata=ToolInvocationMetadata(requires_checkpoint=True),
        ),
        lambda name, args: executed.append((name, args)),
    )

    assert outcome.status == "blocked"
    assert outcome.invocation.metadata.blocked_by == "checkpoint"
    assert outcome.evidence["error_message"] == "checkpoint"
    assert executed == []


def test_pipeline_required_checkpoint_without_hook_is_unverified_and_blocked():
    outcome = ToolInvocationPipeline().run(
        ToolInvocation(
            "write_file",
            {"path": "README.md"},
            metadata=ToolInvocationMetadata(requires_checkpoint=True),
        ),
        lambda name, args: {"should": "not execute"},
    )

    assert outcome.status == "blocked"
    assert outcome.receipt is not None
    assert outcome.evidence["blocked_by"] == "checkpoint"
    assert "unavailable" in outcome.evidence["error_message"]


def test_pipeline_split_completion_cannot_promote_blocked_checkpoint_attempt():
    pipeline = ToolInvocationPipeline()
    materialized, trace = pipeline.begin(
        ToolInvocation(
            "write_file",
            {"path": "README.md"},
            metadata=ToolInvocationMetadata(requires_checkpoint=True),
        )
    )

    outcome = pipeline.complete(materialized, {"written": True}, trace)

    assert outcome.status == "blocked"
    assert outcome.invocation.metadata.blocked_by == "checkpoint"
    assert outcome.evidence["checkpoint_ref"] == ""


def test_pipeline_complete_requires_checkpoint_trace_before_terminal_success():
    outcome = ToolInvocationPipeline().complete(
        ToolInvocation(
            "write_file",
            {"path": "README.md"},
            metadata=ToolInvocationMetadata(requires_checkpoint=True),
        ),
        {"written": True},
        ["resolve", "execute"],
    )

    assert outcome.status == "blocked"
    assert outcome.invocation.metadata.blocked_by == "checkpoint"
    assert "missing" in outcome.evidence["error_message"]
    assert outcome.receipt is not None


def test_pipeline_checkpoint_provenance_is_hashed_and_evidenced():
    checkpoint_payload = {"allow": True, "checkpoint_id": "opaque-secret-handle"}
    outcome = ToolInvocationPipeline(
        hooks={"checkpoint": lambda value, *, attempt: checkpoint_payload}
    ).run(
        ToolInvocation(
            "write_file",
            {"path": "README.md"},
            metadata=ToolInvocationMetadata(requires_checkpoint=True),
        ),
        lambda name, args: {"written": True},
    )

    assert outcome.status == "success"
    assert outcome.evidence["checkpoint_ref"].startswith("sha256:")
    assert "opaque-secret-handle" not in json.dumps(outcome.evidence)
    assert outcome.receipt is not None
    assert outcome.receipt.checkpoint_ref == outcome.evidence["checkpoint_ref"]


def test_pipeline_finalization_hooks_run_once_per_attempt():
    calls = []
    pipeline = ToolInvocationPipeline(
        hooks={
            "persist": lambda value, *, attempt: calls.append("persist") or value,
            "evidence": lambda value, *, attempt: calls.append("evidence") or value,
        }
    )
    invocation = ToolInvocation("demo.tool", {}, tool_call_id="once")

    first = pipeline.complete(invocation, {"ok": True}, ["resolve", "execute"])
    second = pipeline.complete(invocation, {"ok": False}, ["resolve", "execute"])

    assert calls == ["persist", "evidence"]
    assert second.status == first.status == "success"
    assert second.result == first.result == {"ok": True}


def test_pipeline_writes_once_per_attempt_receipt_across_begin_complete_cycle():
    receipts = []
    pipeline = ToolInvocationPipeline(receipt_writer=receipts.append)
    invocation = ToolInvocation(**_fixture("invocation.json"))

    materialized, trace = pipeline.begin(invocation)
    outcome = pipeline.complete(materialized, {"ok": True}, trace)
    duplicate = pipeline.complete(materialized, {"ok": True}, trace)

    assert outcome.status == "success"
    assert duplicate.receipt is not None
    assert outcome.receipt is not None
    assert duplicate.receipt.receipt_id == outcome.receipt.receipt_id
    assert len(receipts) == 1


def test_pipeline_receipt_deduplication_is_by_attempt_not_result_content():
    receipts = []
    pipeline = ToolInvocationPipeline(receipt_writer=receipts.append)
    invocation = _fixture("invocation.json")

    first = pipeline.complete(
        ToolInvocation(**invocation), {"value": 1}, ["resolve", "execute"]
    )
    second = pipeline.complete(
        ToolInvocation(**invocation),
        {"value": 2},
        ["resolve", "execute"],
        status="error",
    )

    assert len(receipts) == 1
    assert second.receipt == first.receipt
    assert second.evidence["receipt_id"] == first.receipt.receipt_id


def test_pipeline_finalization_errors_are_terminal_and_do_not_repeat_persist():
    persisted = []
    pipeline = ToolInvocationPipeline(
        hooks={
            "persist": lambda value, *, attempt: (
                persisted.append(attempt.metadata.attempt_id)
                or (_ for _ in ()).throw(RuntimeError("persist failed"))
            )
        }
    )

    outcome = pipeline.run(
        ToolInvocation("demo.tool", {}), lambda name, args: {"ok": True}
    )

    assert outcome.status == "error"
    assert outcome.error_type == "RuntimeError"
    assert outcome.receipt is not None
    assert outcome.evidence["status"] == "error"
    assert outcome.trace[-2:] == ["persist", "evidence"]
    assert len(persisted) == 1


def test_pipeline_never_executes_a_blocked_attempt_if_persist_fails():
    executed = []
    pipeline = ToolInvocationPipeline(
        hooks={
            "guardrail": lambda value, *, attempt: ToolDecision(
                allow=False, reason="readonly"
            ),
            "persist": lambda value, *, attempt: (_ for _ in ()).throw(
                RuntimeError("persist failed")
            ),
        }
    )

    outcome = pipeline.run(
        ToolInvocation("danger.tool", {}),
        lambda name, args: executed.append((name, args)),
    )

    assert outcome.status == "error"
    assert outcome.invocation.metadata.blocked_by == "guardrail"
    assert executed == []


def test_pipeline_receipt_writer_failure_is_fail_safe_and_evidenced():
    writes = []

    def write(receipt):
        writes.append(receipt)
        raise OSError("receipt store unavailable")

    outcome = ToolInvocationPipeline(receipt_writer=write).run(
        ToolInvocation("demo.tool", {}), lambda name, args: {"ok": True}
    )

    assert outcome.status == "error"
    assert outcome.receipt is not None
    assert outcome.invocation.metadata.receipt_written is False
    assert outcome.evidence["receipt_error_type"] == "OSError"
    assert len(writes) == 1


def test_pipeline_catches_keyboard_interrupt_as_cancelled():
    outcome = ToolInvocationPipeline().run(
        ToolInvocation("demo.tool", {}),
        lambda name, args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert outcome.status == "cancelled"
    assert outcome.error_type == "KeyboardInterrupt"
    assert outcome.receipt is not None
    assert outcome.evidence["status"] == "cancelled"


def test_serial_adapter_uses_serial_default_and_isolates_top_level_args():
    received = []
    adapter = SerialToolExecutorAdapter(
        execute_fn=lambda name, args: received.append(args), label=""
    )
    outcome = ToolInvocationPipeline().run(
        ToolInvocation("demo.tool", {"nested": {"value": 1}}), adapter
    )

    assert outcome.invocation.metadata.executor == "serial"
    assert received == [{"nested": {"value": 1}}]
    assert received[0] is not outcome.invocation.args


def test_pipeline_begin_complete_matches_run_stage_and_evidence_contract():
    invocation = ToolInvocation(**_fixture("invocation.json"))
    result = {"ok": True, "value": "same"}

    direct = ToolInvocationPipeline().run(
        invocation,
        lambda name, args: result,
    )

    split_pipeline = ToolInvocationPipeline()
    materialized, trace = split_pipeline.begin(invocation)
    split = split_pipeline.complete(materialized, result, trace)

    assert direct.trace == split.trace == list(STAGES)
    assert split.evidence["receipt_id"] == direct.evidence["receipt_id"]
    assert split.evidence["tool_call_id"] == direct.evidence["tool_call_id"]
    assert split.receipt is not None
    assert split.receipt.receipt_id == direct.receipt.receipt_id


def test_pipeline_complete_canonicalizes_split_trace_to_bounded_stage_order():
    invocation = ToolInvocation(**_fixture("invocation.json"))
    result = {"ok": True}
    noisy_trace = [
        "normalize",
        "resolve",
        "resolve",
        "unknown",
        "checkpoint",
        "classify",
        "persist",
        "evidence",
    ]

    outcome = ToolInvocationPipeline().complete(invocation, result, noisy_trace)

    assert outcome.trace == [
        "resolve",
        "normalize",
        "classify",
        "checkpoint",
        "persist",
        "evidence",
    ]
    assert outcome.evidence["trace"] == outcome.trace


def test_pipeline_for_agent_accepts_optional_tool_name_for_existing_call_sites():
    agent = type("FakeAgent", (), {})()

    pipeline = pipeline_for_agent(agent, "demo.tool")

    assert isinstance(pipeline, ToolInvocationPipeline)


def test_pipeline_applies_fail_safe_metadata_defaults_and_redacts_external_results():
    receipts = []
    invocation = _fixture("invocation.json")
    external_result = _fixture("external_result.json")
    pipeline = ToolInvocationPipeline(receipt_writer=receipts.append)

    outcome = pipeline.run(
        ToolInvocation(
            name=invocation["name"],
            args=invocation["args"],
            metadata=ToolInvocationMetadata(
                external_result=True,
                extras={"source": "remote-api"},
            ),
        ),
        lambda name, args: external_result,
    )

    assert outcome.status == "success"
    assert outcome.invocation.metadata.attempt_id
    assert outcome.invocation.metadata.executor == "serial"
    assert outcome.invocation.metadata.status == "success"
    assert outcome.evidence["external_result"] is True
    assert outcome.evidence["result"]["secret"] == "[REDACTED]"
    assert outcome.evidence["result"]["nested"]["token"] == "[REDACTED]"
    assert outcome.result["secret"] == "keep-in-live-result"
    assert len(receipts) == 1


def test_default_receipt_writer_uses_hashes_and_existing_receipt_ledger(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HERMES_RECEIPTS_DIR", str(tmp_path))
    receipt = (
        ToolInvocationPipeline()
        .run(
            ToolInvocation("demo.tool", {"token": "live-secret"}),
            lambda name, args: {"password": "live-secret"},
        )
        .receipt
    )

    assert receipt is not None
    stored = default_tool_invocation_receipt_writer(receipt)
    assert stored.sha
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    payload = files[0].read_text(encoding="utf-8")
    assert "live-secret" not in payload
    assert receipt.args_hash in payload
    assert receipt.result_hash in payload


def test_pipeline_normalizes_invalid_metadata_and_completion_status_fail_safe():
    invocation = ToolInvocation(
        "demo.tool",
        {},
        metadata=ToolInvocationMetadata(
            actor="",
            executor="",
            status="not-a-status",
            evidence_version="",
        ),
    )
    outcome = ToolInvocationPipeline().run(invocation, lambda name, args: {"ok": True})
    invalid_completion = ToolInvocationPipeline().complete(
        ToolInvocation("demo.tool", {}), {"ok": True}, [], status="not-a-status"
    )

    assert outcome.status == "success"
    assert outcome.invocation.metadata.actor == "agent"
    assert outcome.invocation.metadata.executor == "serial"
    assert outcome.invocation.metadata.evidence_version == "tool-invocation/v1"
    assert invalid_completion.status == "error"
    assert invalid_completion.evidence["status"] == "error"


def test_pipeline_converts_execution_exception_to_error_outcome():
    outcome = ToolInvocationPipeline().run(
        ToolInvocation("demo.tool", {}),
        lambda name, args: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert outcome.status == "error"
    assert outcome.error_type == "RuntimeError"
    assert outcome.trace[-2:] == ["persist", "evidence"]


def test_pipeline_blocks_fabricated_result_at_tool_boundary_and_receipts_verdict():
    receipts = []

    def watcher(attempt):
        return watch_result_boundary(
            attempt.result,
            lambda: {"ok": False},
            kind="tool-result",
            subject=attempt.resolved_name,
        )

    outcome = ToolInvocationPipeline(
        watcher=watcher,
        receipt_writer=receipts.append,
    ).run(
        ToolInvocation("demo.tool", {}),
        lambda name, args: {"ok": True},
    )

    assert outcome.status == "blocked"
    assert outcome.result["error"] == "watcher gate blocked fabricated result"
    assert outcome.evidence["provenance"] == "UNVERIFIED"
    assert outcome.evidence["watcher"]["verdict"] == Verdict.FABRICATED.value
    assert outcome.invocation.metadata.blocked_by == "watcher-gate"
    assert receipts[0].meta["provenance"] == "UNVERIFIED"
    assert receipts[0].meta["watcher_verdict"] == Verdict.FABRICATED.value


def test_pipeline_marks_missing_recompute_unverified_in_receipt_and_evidence():
    receipts = []
    outcome = ToolInvocationPipeline(receipt_writer=receipts.append).run(
        ToolInvocation("remote.tool", {}),
        lambda name, args: {"ok": True},
    )

    assert outcome.status == "success"
    assert outcome.evidence["provenance"] == "UNVERIFIED"
    assert outcome.evidence["watcher"]["verdict"] == Verdict.UNVERIFIED.value
    assert receipts[0].meta["provenance"] == "UNVERIFIED"


def test_pipeline_measured_watcher_provenance_is_available_to_trajectory():
    def watcher(attempt):
        return watch_result_boundary(
            attempt.result,
            lambda: {"ok": True},
            kind="tool-result",
            subject=attempt.resolved_name,
        )

    outcome = ToolInvocationPipeline(watcher=watcher).run(
        ToolInvocation("demo.tool", {}, tool_call_id="call-1"),
        lambda name, args: {"ok": True},
    )

    assert outcome.evidence["provenance"] == Verdict.MEASURED.value
    assert outcome.evidence["watcher"]["matches"] is True


def test_trajectory_carries_tool_boundary_provenance():
    from agent.agent_runtime_helpers import convert_to_trajectory_format

    agent = SimpleNamespace(
        _tool_result_provenance={
            "call-1": {
                "provenance": "MEASURED",
                "verdict": "MEASURED",
                "matches": True,
                "reason": "reported value matches the local recomputation",
            }
        },
        _format_tools_for_system_message=lambda: "",
        _toon_prompts_enabled=False,
    )
    messages = [
        {"role": "user", "content": "check"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {"name": "demo.tool", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"ok": true}',
        },
    ]

    trajectory = convert_to_trajectory_format(agent, messages, "check", True)

    tool_value = trajectory[-1]["value"]
    assert '"provenance": {"provenance": "MEASURED"' in tool_value


def test_pipeline_for_agent_accepts_tool_name_from_tool_dispatch():
    from types import SimpleNamespace

    from agent.tool_invocation_pipeline import pipeline_for_agent

    pipeline = pipeline_for_agent(SimpleNamespace(), "read_file")

    assert isinstance(pipeline, ToolInvocationPipeline)
