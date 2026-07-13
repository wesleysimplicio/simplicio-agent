"""Deterministic golden-path harness for issue #211.

This module exercises the two production contracts introduced in the
surrounding slices without widening either of them:

* :class:`agent.task_envelope.TaskEnvelope` remains the canonical lifecycle
  state machine.
* :class:`tools.simplicio_transport.SimplicioTransport` remains the only
  transport boundary.

The harness is fixture-driven and deliberately small. It records durable
receipts for the lease, mutation, validation, evidence, and delivery phases,
then performs an independent final-state requery from disk before closing the
envelope.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from agent.task_envelope import TaskEnvelope, TaskState
from agent.telemetry.receipts import Receipt, receipt_path, record_receipt
from tools.simplicio_transport import SimplicioTransport, TransportReceipt


class GoldenPathError(RuntimeError):
    """Raised when the deterministic golden path cannot be completed."""


@dataclass(frozen=True)
class GoldenPathMutation:
    """One deterministic file mutation inside the fixture workspace."""

    path: str
    expected_before: str
    expected_after: str


@dataclass(frozen=True)
class GoldenPathScenario:
    """Fixture-backed golden-path input."""

    fixture_root: Path
    name: str
    repo: str
    branch: str
    scope: str
    acceptance_criteria: tuple[str, ...]
    worker: str
    lease: str
    delivery_target: str
    write_set: tuple[str, ...]
    validation_command: str
    mutation: GoldenPathMutation
    yool_prefix: str = "agent.golden_path"

    @classmethod
    def from_path(cls, fixture_root: str | Path) -> "GoldenPathScenario":
        root = Path(fixture_root).resolve()
        payload = json.loads((root / "scenario.json").read_text(encoding="utf-8"))
        mutation = payload["mutation"]
        return cls(
            fixture_root=root,
            name=str(payload["name"]),
            repo=str(payload["repo"]),
            branch=str(payload["branch"]),
            scope=str(payload["scope"]),
            acceptance_criteria=tuple(payload["acceptance_criteria"]),
            worker=str(payload["worker"]),
            lease=str(payload["lease"]),
            delivery_target=str(payload["delivery_target"]),
            write_set=tuple(str(item) for item in payload["write_set"]),
            validation_command=str(payload["validation_command"]),
            mutation=GoldenPathMutation(
                path=str(mutation["path"]),
                expected_before=str(mutation["expected_before"]),
                expected_after=str(mutation["expected_after"]),
            ),
            yool_prefix=str(payload.get("yool_prefix") or "agent.golden_path"),
        )

    @property
    def workspace_root(self) -> Path:
        return self.fixture_root / "workspace"

    @property
    def receipts_root(self) -> Path:
        return self.workspace_root / ".receipts"

    @property
    def absolute_write_set(self) -> tuple[Path, ...]:
        return tuple((self.fixture_root / item).resolve() for item in self.write_set)

    @property
    def mutation_path(self) -> Path:
        return (self.fixture_root / self.mutation.path).resolve()

    def mechanical_edit_plan(self) -> dict[str, Any]:
        return {
            "write_set": [str(path) for path in self.absolute_write_set],
            "mutation": {
                "path": str(self.mutation_path),
                "expected_before": self.mutation.expected_before,
                "expected_after": self.mutation.expected_after,
            },
        }

    def expected_final_state(self) -> dict[str, str]:
        return {self.mutation.path: self.mutation.expected_after}


@dataclass(frozen=True)
class GoldenPathResult:
    """Structured outcome from one deterministic harness run."""

    scenario: GoldenPathScenario
    envelope: TaskEnvelope
    transport_health: dict[str, Any]
    transport_receipts: dict[str, TransportReceipt]
    receipt_refs: dict[str, str]
    receipt_files: dict[str, str]
    final_state: dict[str, str]
    requery: dict[str, Any]
    fallback_events: tuple[dict[str, Any], ...]


def _receipt_ref(receipt: Receipt) -> str:
    return f"receipt://{receipt.sha}"


def _apply_mutation(scenario: GoldenPathScenario) -> dict[str, Any]:
    target = scenario.mutation_path
    current = target.read_text(encoding="utf-8")
    if current != scenario.mutation.expected_before:
        raise GoldenPathError(
            f"unexpected pre-edit content for {target}: "
            f"{current!r} != {scenario.mutation.expected_before!r}"
        )
    target.write_text(scenario.mutation.expected_after, encoding="utf-8")
    return {
        "applied": True,
        "files_modified": [str(target)],
        "write_set": [str(path) for path in scenario.absolute_write_set],
    }


def _validate_workspace(scenario: GoldenPathScenario) -> dict[str, Any]:
    observed = scenario.mutation_path.read_text(encoding="utf-8")
    matches = observed == scenario.mutation.expected_after
    return {
        "decision": "allow" if matches else "deny",
        "target": str(scenario.mutation_path),
        "matches_expected": matches,
        "observed": observed,
        "expected": scenario.mutation.expected_after,
    }


def build_fixture_mcp_call(
    scenario: GoldenPathScenario,
) -> Callable[[str, dict[str, Any]], Any]:
    """Return a deterministic fallback transport for the fixture scenario."""

    def _call(operation: str, args: dict[str, Any]) -> Any:
        if operation == "orient":
            return {
                "repo": str(scenario.workspace_root),
                "format": args.get("fmt", "json"),
                "write_set": [str(path) for path in scenario.absolute_write_set],
            }
        if operation == "checkpoint":
            return {
                "label": args["label"],
                "lease": scenario.lease,
                "workdir": args.get("workdir", ""),
                "write_set": [str(path) for path in scenario.absolute_write_set],
            }
        if operation == "mechanical_edit":
            return _apply_mutation(scenario)
        if operation == "gate":
            result = _validate_workspace(scenario)
            result["command"] = args["command"]
            return result
        if operation == "ledger":
            return {"accepted": True, "event": args["event"]}
        raise GoldenPathError(f"unsupported fixture MCP operation: {operation}")

    return _call


class GoldenPathHarness:
    """Drive one bounded deterministic task through the golden path."""

    def __init__(
        self,
        scenario: GoldenPathScenario,
        *,
        cli_bin: Optional[str] = None,
        mcp_call: Optional[Callable[[str, dict[str, Any]], Any]] = None,
        timeout_s: float = 20.0,
    ) -> None:
        self.scenario = scenario
        self.transport = SimplicioTransport(
            cli_bin=cli_bin,
            mcp_call=mcp_call,
            timeout_s=timeout_s,
        )
        self._receipt_refs: dict[str, str] = {}
        self._receipt_files: dict[str, str] = {}
        self._transport_receipts: dict[str, TransportReceipt] = {}

    @classmethod
    def from_fixture(
        cls,
        fixture_root: str | Path,
        *,
        cli_bin: Optional[str] = None,
        mcp_call: Optional[Callable[[str, dict[str, Any]], Any]] = None,
        timeout_s: float = 20.0,
    ) -> "GoldenPathHarness":
        return cls(
            GoldenPathScenario.from_path(fixture_root),
            cli_bin=cli_bin,
            mcp_call=mcp_call,
            timeout_s=timeout_s,
        )

    def run(self) -> GoldenPathResult:
        task_id = f"golden-{uuid.uuid4().hex}"
        envelope = TaskEnvelope.create(
            repo=self.scenario.repo,
            branch=self.scenario.branch,
            scope=self.scenario.scope,
            acceptance_criteria=self.scenario.acceptance_criteria,
            model="golden-path-harness",
            task_id=task_id,
            correlation_id=self.scenario.name,
            write_set=[str(path) for path in self.scenario.absolute_write_set],
        )

        orient = self._require_ok(
            "orient",
            self.transport.orient(str(self.scenario.workspace_root), fmt="json"),
        )
        envelope = envelope.transition(
            TaskState.ORIENTED,
            receipts=[self._record_step("orient", orient.to_dict())],
        )

        plan_payload = {
            "task_id": task_id,
            "write_set": [str(path) for path in self.scenario.absolute_write_set],
            "delivery_target": self.scenario.delivery_target,
        }
        envelope = envelope.transition(
            TaskState.PLANNED,
            receipts=[self._record_step("plan", plan_payload)],
        )

        lease = self._require_ok(
            "lease",
            self.transport.checkpoint(
                "golden-path-lease",
                workdir=str(self.scenario.workspace_root),
                extra={
                    "lease": self.scenario.lease,
                    "write_set": [
                        str(path) for path in self.scenario.absolute_write_set
                    ],
                },
            ),
        )
        envelope = envelope.transition(
            TaskState.CLAIMED,
            worker=self.scenario.worker,
            lease=self.scenario.lease,
            receipts=[self._record_step("lease", lease.to_dict())],
        )

        mutation = self._require_ok(
            "mutation",
            self.transport.mechanical_edit(self.scenario.mechanical_edit_plan()),
        )
        modified = tuple(sorted(str(item) for item in mutation.value["files_modified"]))
        expected_write_set = tuple(
            sorted(str(path) for path in self.scenario.absolute_write_set)
        )
        if modified != expected_write_set:
            raise GoldenPathError(
                f"write_set mismatch: modified {modified!r} != expected {expected_write_set!r}"
            )
        envelope = envelope.transition(
            TaskState.EXECUTING,
            artifacts=list(modified),
            receipts=[self._record_step("mutation", mutation.to_dict())],
        )

        validation = self._require_ok(
            "validation",
            self.transport.gate(
                self.scenario.validation_command,
                description="golden path validation",
                session_key=task_id,
            ),
        )
        envelope = envelope.transition(
            TaskState.VALIDATING,
            receipts=[self._record_step("validation", validation.to_dict())],
        )

        requery = self._requery_final_state()
        requery_ref = self._record_step("requery", requery)
        if (
            validation.value.get("decision") != "allow"
            or not requery["matches_expected"]
        ):
            raise GoldenPathError("golden path did not produce a verified final state")
        evidence_payload = {
            "validation_receipt": self._receipt_refs["validation"],
            "requery_receipt": requery_ref,
            "final_state": requery["observed"],
        }
        evidence_ref = self._record_step("evidence", evidence_payload)
        envelope = envelope.transition(
            TaskState.EVIDENCE_READY,
            receipts=[evidence_ref],
            evidence_refs=[
                self._receipt_refs["validation"],
                requery_ref,
                evidence_ref,
            ],
        )

        delivery = self._require_ok(
            "delivery",
            self.transport.ledger({
                "task_id": task_id,
                "delivery_target": self.scenario.delivery_target,
                "evidence_refs": list(envelope.evidence_refs),
            }),
        )
        if (
            not isinstance(delivery.value, dict)
            or delivery.value.get("accepted") is not True
        ):
            raise GoldenPathError("delivery acknowledgment was not accepted")
        delivery_ref = self._record_step("delivery", delivery.to_dict())
        envelope = envelope.transition(
            TaskState.DELIVERED,
            receipts=[delivery_ref],
            delivery_target=self.scenario.delivery_target,
        )
        envelope = envelope.transition(TaskState.CLOSED)

        return GoldenPathResult(
            scenario=self.scenario,
            envelope=envelope,
            transport_health=self.transport.health(),
            transport_receipts=dict(self._transport_receipts),
            receipt_refs=dict(self._receipt_refs),
            receipt_files=dict(self._receipt_files),
            final_state=requery["observed"],
            requery=requery,
            fallback_events=self.transport.fallback_events,
        )

    def _record_step(self, step: str, payload: dict[str, Any]) -> str:
        receipt = record_receipt(
            payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            yool_id=f"{self.scenario.yool_prefix}.{step}",
            lane="fast",
            status="ok",
            meta={"scenario": self.scenario.name, "step": step},
            directory=self.scenario.receipts_root,
        )
        ref = _receipt_ref(receipt)
        self._receipt_refs[step] = ref
        self._receipt_files[step] = str(
            receipt_path(receipt.sha, self.scenario.receipts_root)
        )
        return ref

    def _require_ok(self, step: str, receipt: TransportReceipt) -> TransportReceipt:
        self._transport_receipts[step] = receipt
        if receipt.ok:
            return receipt
        raise GoldenPathError(
            f"{step} failed via {receipt.transport}: "
            f"{receipt.error.code if receipt.error else 'unknown_error'}"
        )

    def _requery_final_state(self) -> dict[str, Any]:
        observed: dict[str, str] = {}
        expected = self.scenario.expected_final_state()
        for relative_path in self.scenario.write_set:
            absolute = (self.scenario.fixture_root / relative_path).resolve()
            observed[relative_path] = absolute.read_text(encoding="utf-8")
        return {
            "write_set": list(self.scenario.write_set),
            "observed": observed,
            "expected": expected,
            "matches_expected": observed == expected,
        }


__all__ = [
    "GoldenPathError",
    "GoldenPathHarness",
    "GoldenPathMutation",
    "GoldenPathResult",
    "GoldenPathScenario",
    "build_fixture_mcp_call",
]
