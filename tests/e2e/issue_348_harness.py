"""Fixture-backed issue-to-plan-to-change-to-tests E2E harness."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agent.task_envelope import TaskEnvelope, TaskLedger, TaskState
from agent.telemetry.receipts import record_receipt
from tools.simplicio_transport import SimplicioTransport, TransportReceipt


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "e2e" / "issue-348"


@dataclass(frozen=True)
class Issue348Scenario:
    fixture_root: Path
    issue_id: str
    name: str
    repo: str
    branch: str
    scope: str
    acceptance_criteria: tuple[str, ...]
    worker: str
    lease: str
    delivery_target: str
    validation_command: str
    write_set: tuple[str, ...]
    plan: dict[str, Any]
    mutation: dict[str, str]
    tool_outcomes: dict[str, str]

    @classmethod
    def from_fixture(cls, root: Path = FIXTURE_ROOT) -> "Issue348Scenario":
        data = json.loads((root / "scenario.json").read_text(encoding="utf-8"))
        return cls(
            fixture_root=root,
            issue_id=str(data["issue_id"]),
            name=str(data["name"]),
            repo=str(data["repo"]),
            branch=str(data["branch"]),
            scope=str(data["scope"]),
            acceptance_criteria=tuple(data["acceptance_criteria"]),
            worker=str(data["worker"]),
            lease=str(data["lease"]),
            delivery_target=str(data["delivery_target"]),
            validation_command=str(data["validation_command"]),
            write_set=tuple(data["write_set"]),
            plan=dict(data["plan"]),
            mutation={key: str(value) for key, value in data["mutation"].items()},
            tool_outcomes={
                key: str(value) for key, value in data["tool_outcomes"].items()
            },
        )

    @property
    def mutation_relative_path(self) -> str:
        return self.mutation["path"]


@dataclass(frozen=True)
class Issue348Run:
    scenario: Issue348Scenario
    workspace: Path
    envelope: TaskEnvelope
    ledger: TaskLedger
    receipts: dict[str, str]
    transport_receipts: dict[str, TransportReceipt]
    test_process: subprocess.CompletedProcess[str]
    final_state: str


def make_transport(
    *, cli_bin: str, timeout_s: float, mcp_call: Any = None
) -> SimplicioTransport:
    """Build a fixture transport without Windows console/job flags.

    The pytest worker itself may run inside a Windows job that rejects
    ``CREATE_NO_WINDOW``. This is a harness-only subprocess detail; transport
    semantics and receipts remain the production implementation.
    """

    transport = SimplicioTransport(
        cli_bin=cli_bin, timeout_s=timeout_s, mcp_call=mcp_call
    )
    if sys.platform == "win32":
        transport._windows_flags = lambda: {}  # type: ignore[method-assign]
    return transport


def _fixture_mcp_call(scenario: Issue348Scenario, fixture_copy: Path):
    def call(operation: str, args: dict[str, Any]) -> Any:
        if operation == "orient":
            return {
                "format": args.get("fmt", "json"),
                "write_set": list(scenario.write_set),
            }
        if operation == "checkpoint":
            return {"accepted": True, "checkpoint": scenario.lease}
        if operation == "mechanical_edit":
            plan = args["plan"]
            mutation = plan["mutation"]
            target = Path(mutation["path"])
            assert target.read_text(encoding="utf-8") == mutation["expected_before"]
            target.write_text(mutation["expected_after"], encoding="utf-8")
            return {"applied": True, "files_modified": [str(target)]}
        if operation == "gate":
            return {"decision": "allow", "command": args["command"]}
        if operation == "ledger":
            return {"accepted": True, "event": args["event"]}
        raise AssertionError(f"unsupported fixture operation: {operation}")

    return call


def _receipt(step: str, payload: Any, receipts_root: Path) -> str:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    saved = record_receipt(
        payload=content,
        yool_id=f"agent.issue_348.{step}",
        lane="fast",
        status="ok",
        meta={"issue_id": "348", "step": step},
        directory=receipts_root,
    )
    return f"receipt://{saved.sha}"


def _append(ledger: TaskLedger, envelope: TaskEnvelope) -> TaskEnvelope:
    ledger.append(envelope)
    return envelope


def _require_ok(
    receipts: dict[str, TransportReceipt], step: str, receipt: TransportReceipt
) -> TransportReceipt:
    receipts[step] = receipt
    assert receipt.ok, receipt.to_dict()
    return receipt


def run_issue_348(fixture_root: Path, tmp_path: Path) -> Issue348Run:
    """Run the complete bounded path against a copied fixture workspace."""

    scenario = Issue348Scenario.from_fixture(fixture_root)
    fixture_copy = tmp_path / "issue-348"
    shutil.copytree(fixture_root, fixture_copy)
    workspace = fixture_copy / "workspace"
    receipts_root = workspace / ".receipts"
    transport = make_transport(
        cli_bin=str(tmp_path / "unavailable-simplicio"),
        timeout_s=2.0,
        mcp_call=_fixture_mcp_call(scenario, fixture_copy),
    )
    transport_receipts: dict[str, TransportReceipt] = {}
    receipts: dict[str, str] = {}
    ledger = TaskLedger()
    absolute_write_set = tuple(
        str((fixture_copy / item).resolve()) for item in scenario.write_set
    )
    envelope = TaskEnvelope.create(
        repo=scenario.repo,
        branch=scenario.branch,
        scope=scenario.scope,
        acceptance_criteria=scenario.acceptance_criteria,
        model="issue-348-e2e",
        task_id=f"issue-{scenario.issue_id}-e2e",
        correlation_id=scenario.name,
        write_set=absolute_write_set,
        now_ns=1,
    )
    ledger.append(envelope)
    receipts["issue"] = _receipt("issue", scenario.__dict__, receipts_root)

    orient = _require_ok(
        transport_receipts,
        "orient",
        transport.orient(str(workspace), fmt="json"),
    )
    receipts["orient"] = _receipt("orient", orient.to_dict(), receipts_root)
    envelope = _append(
        ledger,
        envelope.transition(
            TaskState.ORIENTED, receipts=[receipts["orient"]], now_ns=2
        ),
    )

    plan = dict(scenario.plan)
    plan["issue_id"] = scenario.issue_id
    plan["write_set"] = list(absolute_write_set)
    plan["mutation"] = {
        **scenario.mutation,
        "path": str((fixture_copy / scenario.mutation_relative_path).resolve()),
    }
    plan_path = workspace / "issue-348-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    receipts["plan"] = _receipt("plan", plan, receipts_root)
    envelope = _append(
        ledger,
        envelope.transition(TaskState.PLANNED, receipts=[receipts["plan"]], now_ns=3),
    )

    checkpoint = _require_ok(
        transport_receipts,
        "checkpoint",
        transport.checkpoint(
            "issue-348-e2e",
            workdir=str(workspace),
            extra={"lease": scenario.lease, "write_set": list(absolute_write_set)},
        ),
    )
    receipts["checkpoint"] = _receipt("checkpoint", checkpoint.to_dict(), receipts_root)
    envelope = _append(
        ledger,
        envelope.transition(
            TaskState.CLAIMED,
            worker=scenario.worker,
            lease=scenario.lease,
            receipts=[receipts["checkpoint"]],
            now_ns=4,
        ),
    )

    mutation = _require_ok(
        transport_receipts,
        "mutation",
        transport.mechanical_edit(plan),
    )
    modified = tuple(sorted(str(item) for item in mutation.value["files_modified"]))
    assert modified == tuple(sorted(absolute_write_set))
    receipts["mutation"] = _receipt("mutation", mutation.to_dict(), receipts_root)
    envelope = _append(
        ledger,
        envelope.transition(
            TaskState.EXECUTING,
            artifacts=list(modified),
            receipts=[receipts["mutation"]],
            now_ns=5,
        ),
    )

    gate = _require_ok(
        transport_receipts,
        "gate",
        transport.gate(scenario.validation_command, session_key=envelope.task_id),
    )
    assert gate.value["decision"] == "allow"
    test_file = workspace / "tests" / "test_state.py"
    test_rc = pytest.main(["-q", str(test_file)], plugins=[])
    test_process = subprocess.CompletedProcess(
        args=[sys.executable, "-m", "pytest", str(test_file), "-q"],
        returncode=int(test_rc),
        stdout="fixture test executed through pytest.main",
        stderr="",
    )
    assert test_process.returncode == 0, test_process.stdout + test_process.stderr
    receipts["tests"] = _receipt(
        "tests",
        {"command": scenario.validation_command, "stdout": test_process.stdout},
        receipts_root,
    )
    envelope = _append(
        ledger,
        envelope.transition(
            TaskState.VALIDATING, receipts=[receipts["tests"]], now_ns=6
        ),
    )

    observed = (fixture_copy / scenario.mutation_relative_path).read_text(
        encoding="utf-8"
    )
    assert observed == scenario.mutation["expected_after"]
    receipts["requery"] = _receipt(
        "requery",
        {"path": scenario.mutation_relative_path, "observed": observed},
        receipts_root,
    )
    receipts["evidence"] = _receipt(
        "evidence",
        {"tests": receipts["tests"], "requery": receipts["requery"]},
        receipts_root,
    )
    envelope = _append(
        ledger,
        envelope.transition(
            TaskState.EVIDENCE_READY,
            evidence_refs=[
                receipts["tests"],
                receipts["requery"],
                receipts["evidence"],
            ],
            receipts=[receipts["evidence"]],
            now_ns=7,
        ),
    )

    delivery = _require_ok(
        transport_receipts,
        "delivery",
        transport.ledger({
            "task_id": envelope.task_id,
            "delivery_target": scenario.delivery_target,
            "evidence_refs": list(envelope.evidence_refs),
        }),
    )
    assert delivery.value["accepted"] is True
    receipts["delivery"] = _receipt("delivery", delivery.to_dict(), receipts_root)
    envelope = _append(
        ledger,
        envelope.transition(
            TaskState.DELIVERED,
            delivery_target=scenario.delivery_target,
            receipts=[receipts["delivery"]],
            now_ns=8,
        ),
    )
    envelope = ledger.close_if_verified(
        envelope, verified_evidence_refs=envelope.evidence_refs
    )
    receipts["close"] = _receipt("close", envelope.ledger_record(), receipts_root)
    return Issue348Run(
        scenario=scenario,
        workspace=workspace,
        envelope=envelope,
        ledger=ledger,
        receipts=receipts,
        transport_receipts=transport_receipts,
        test_process=test_process,
        final_state=observed,
    )


__all__ = [
    "FIXTURE_ROOT",
    "Issue348Run",
    "Issue348Scenario",
    "make_transport",
    "run_issue_348",
]
