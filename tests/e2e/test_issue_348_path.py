"""Issue #348 fixture-driven E2E coverage.

The tests keep the external boundary honest: normal calls use the CLI-shaped
transport, failures remain typed receipts, and only a copied fixture workspace
is mutated.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent.task_envelope import TaskEnvelope, TaskLedger, TaskState
from agent.tool_invocation_pipeline import ToolInvocation, ToolInvocationPipeline
from tests.e2e.issue_348_harness import (
    FIXTURE_ROOT,
    Issue348Scenario,
    make_transport,
    run_issue_348,
)

pytestmark = pytest.mark.live_system_guard_bypass


def test_issue_fixture_reaches_closed_only_after_tests_and_requery(tmp_path: Path):
    result = run_issue_348(FIXTURE_ROOT, tmp_path)

    assert result.envelope.state is TaskState.CLOSED
    assert result.envelope.attempts == 1
    assert result.final_state == result.scenario.mutation["expected_after"]
    assert {
        "issue",
        "orient",
        "plan",
        "checkpoint",
        "mutation",
        "tests",
        "requery",
        "evidence",
        "delivery",
        "close",
    } <= set(result.receipts)
    assert result.ledger.history(result.envelope.task_id)[-1]["state"] == "closed"
    assert all(receipt.ok for receipt in result.transport_receipts.values())
    assert result.test_process.returncode == 0


@pytest.mark.parametrize("mode", ["unavailable", "permission", "timeout", "invalid"])
def test_issue_fixture_records_uniform_tool_outcomes(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    scenario = Issue348Scenario.from_fixture()
    if mode == "unavailable":
        fallback_calls: list[str] = []

        def fallback(operation: str, _args: dict) -> dict:
            fallback_calls.append(operation)
            return {"fallback": True}

        transport = make_transport(
            cli_bin=str(tmp_path / "missing-simplicio"),
            timeout_s=2.0,
            mcp_call=fallback,
        )
        receipt = transport.gate("fixture-test")
        assert receipt.ok is True
        assert receipt.transport == "mcp"
        assert receipt.fallback_reason == "cli_unavailable"
        assert fallback_calls == ["gate"]
        return

    expected_code = scenario.tool_outcomes[mode]

    def failure(_operation: str, _args: dict):
        from tools.simplicio_transport import TransportError, TransportReceipt

        return TransportReceipt.failure(
            "gate",
            TransportError(
                expected_code,
                f"fixture {mode} outcome",
                retryable=mode == "timeout",
            ),
            transport="mcp",
        )

    receipt = make_transport(
        cli_bin=str(tmp_path / "missing-simplicio"),
        timeout_s=2.0,
        mcp_call=failure,
    ).gate("fixture-test")

    assert receipt.ok is False
    assert receipt.transport == "mcp"
    assert receipt.fallback_reason == "cli_unavailable"
    assert receipt.error is not None
    assert receipt.error.code == expected_code
    assert receipt.error.retryable is (mode == "timeout")


def test_invalid_tool_is_error_receipted_and_does_not_raise():
    pipeline = ToolInvocationPipeline()
    invocation = ToolInvocation(
        name="fixture.missing_tool",
        args={"issue_id": "348"},
        tool_call_id="tool-call-348",
        task_id="issue-348-e2e",
    )

    def execute(_name: str, _args: dict) -> object:
        raise LookupError("invalid tool: fixture.missing_tool")

    outcome = pipeline.run(invocation, execute)

    assert outcome.status == "error"
    assert outcome.error_type == "LookupError"
    assert outcome.receipt is not None
    assert outcome.receipt.status == "error"
    assert outcome.evidence["error_type"] == "LookupError"
    assert "persist" in outcome.trace
    assert "evidence" in outcome.trace


def test_blocked_resume_round_trip_is_idempotent_under_concurrent_replay():
    envelope = TaskEnvelope.create(
        repo="tests/fixtures/e2e/issue-348",
        branch="e2e/issue-348",
        scope="fixture:issue-348",
        acceptance_criteria=["resume safely"],
        task_id="issue-348-resume",
        now_ns=1,
    )
    ledger = TaskLedger()
    ledger.append(envelope)
    oriented = envelope.transition(TaskState.ORIENTED, now_ns=2)
    planned = oriented.transition(TaskState.PLANNED, now_ns=3)
    ledger.append(planned)
    blocked = planned.transition(
        TaskState.BLOCKED, block_reason="tool unavailable", now_ns=4
    )
    ledger.append(blocked)
    resumed = TaskEnvelope.from_json(blocked.to_json()).transition(
        TaskState.ORIENTED, now_ns=5
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: ledger.append(resumed), range(32)))

    history = ledger.history(envelope.task_id)
    resumed_records = [record for record in history if record["state"] == "oriented"]
    assert len(resumed_records) == 1
    assert TaskEnvelope.from_json(blocked.to_json()).state is TaskState.BLOCKED


def test_transport_calls_are_safe_to_concurrently_replay(tmp_path: Path):
    transport = make_transport(
        cli_bin=str(tmp_path / "missing-simplicio"),
        timeout_s=2.0,
        mcp_call=lambda operation, _args: {"operation": operation, "accepted": True},
    )

    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(
            pool.map(lambda _index: transport.gate("fixture-test"), range(12))
        )

    assert all(receipt.ok for receipt in receipts)
    assert len({receipt.request_id for receipt in receipts}) == 12
    assert transport.health()["calls"] == 12
