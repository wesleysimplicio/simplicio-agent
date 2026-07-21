#!/usr/bin/env python3
"""Deterministic Software Builder orchestration manifest (issue #151).

This module describes the bounded vertical slice between the existing goal,
task, transport, and loop receipt contracts.  It is intentionally a manifest
validator, not a second executor: Mapper, Dev CLI, Runtime, and the loop keep
owning their work and emit their own receipts.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

# Direct script execution puts ``tools/`` on ``sys.path`` rather than the
# repository root.  Keep the CLI usable without requiring an installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.goal_contract import Evidence, GoalContract, WatcherRequirement
from agent.task_envelope import TaskEnvelope, TaskState

SCHEMA = "simplicio.software-builder-manifest/v1"
OPERATORS = ("mapper", "dev_cli", "runtime", "loop")
FOUNDATION_STATUS = "fixture_only"
AUDIT_SCHEMA = "simplicio.software-builder-audit/v1"

_SOURCE_CONTRACTS = {
    "agent/goal_contract.py": ("class GoalContract",),
    "agent/task_envelope.py": ("class TaskEnvelope", "EVIDENCE_READY"),
    "tools/simplicio_transport.py": ("class SimplicioTransport", "def gate"),
    "skills/simplicio-loop/simplicio-tasks/references/orchestration.md": (
        "attach_evidence",
    ),
}


def _receipt(operator: str) -> str:
    return f"receipt://software-builder/fixture/{operator}"


def _goal_contract() -> dict[str, Any]:
    goal = GoalContract(
        objective="prove the bounded Software Builder orchestration seam",
        acceptance_criteria=(
            "goal contract carries acceptance criteria and backlog metadata",
            "mapper and dev-cli context/edit receipts are linked",
            "runtime gate/checkpoint/ledger receipts are linked",
            "loop journal and watcher receipts remain explicit",
        ),
        contract_id="software-builder-fixture-goal",
        created_at_ns=1,
        updated_at_ns=1,
        reason="bounded foundation fixture; product delivery not attempted",
        evidence=tuple(
            Evidence(
                _receipt(operator),
                kind=f"{operator}_receipt",
                verified=False,
            )
            for operator in OPERATORS
        ),
        watchers=(WatcherRequirement("loop-watcher", required=True),),
    )
    return goal.to_dict()


def _task_envelope(receipts: tuple[str, ...]) -> dict[str, Any]:
    envelope = TaskEnvelope.create(
        repo="fixture/software-builder",
        branch="fixture/software-builder-v1",
        scope="bounded orchestration manifest only",
        write_set=("tools/software_builder_manifest.py",),
        acceptance_criteria=(
            "goal contract is present",
            "all four operator receipts are linked",
            "delivery remains explicitly unattempted",
        ),
        risk_policy="no-clean-machine-delivery-claim",
        model="fixture",
        execution_policy="existing-apis-only",
        task_id="software-builder-fixture-task",
        correlation_id="software-builder-fixture-run",
        now_ns=1,
    )
    for state, now_ns in (
        (TaskState.ORIENTED, 2),
        (TaskState.PLANNED, 3),
        (TaskState.CLAIMED, 4),
        (TaskState.EXECUTING, 5),
        (TaskState.VALIDATING, 6),
    ):
        envelope = envelope.transition(state, now_ns=now_ns)
    envelope = envelope.transition(
        TaskState.EVIDENCE_READY,
        receipts=receipts,
        evidence_refs=receipts,
        artifacts=(
            "tools/software_builder_manifest.py",
            "fixtures/software-builder/v1-foundation.json",
            "docs/architecture/software-builder-e2e-foundation.md",
        ),
        now_ns=7,
    )
    return envelope.to_dict()


def _stages() -> list[dict[str, Any]]:
    return [
        {
            "name": "mapper",
            "operator": "simplicio-mapper",
            "operation": "scan → inspect → handoff",
            "input": "goal_contract.objective",
            "output": "context-pack",
            "receipt": _receipt("mapper"),
            "status": FOUNDATION_STATUS,
            "verified": False,
        },
        {
            "name": "dev_cli",
            "operator": "simplicio-dev-cli",
            "operation": "task / deterministic_edit",
            "input": "mapper.context-pack",
            "output": "bounded mechanical diff + test result",
            "receipt": _receipt("dev_cli"),
            "status": FOUNDATION_STATUS,
            "verified": False,
        },
        {
            "name": "runtime",
            "operator": "simplicio",
            "operation": "gate → checkpoint → ledger",
            "input": "dev_cli.diff-and-tests",
            "output": "action-gate and ledger receipt",
            "receipt": _receipt("runtime"),
            "status": FOUNDATION_STATUS,
            "verified": False,
        },
        {
            "name": "loop",
            "operator": "simplicio-loop",
            "operation": "journal → watcher → bounded continuation",
            "input": "runtime.receipt",
            "output": "journal and watcher receipt",
            "receipt": _receipt("loop"),
            "status": FOUNDATION_STATUS,
            "verified": False,
        },
    ]


def build_foundation_manifest(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Return the host-independent v1 fixture document."""

    del repo_root  # accepted for parity with other repository manifest APIs
    receipts = tuple(_receipt(operator) for operator in OPERATORS)
    return {
        "schema": SCHEMA,
        "version": 1,
        "manifest_id": "software-builder-foundation-v1",
        "status": FOUNDATION_STATUS,
        "goal_contract": _goal_contract(),
        "backlog": {
            "acceptance_criteria": [
                "goal contract carries acceptance criteria and backlog metadata",
                "mapper and dev-cli context/edit receipts are linked",
                "runtime gate/checkpoint/ledger receipts are linked",
                "loop journal and watcher receipts remain explicit",
            ],
            "dependencies": [
                "simplicio-mapper on PATH",
                "simplicio-dev-cli on PATH",
                "simplicio Runtime CLI or explicit MCP fallback",
                "simplicio-loop bounded journal and watcher",
            ],
            "risks": [
                "cross-repository versions may drift",
                "a receipt reference is not proof that its producer ran",
                "UI, clean-machine, packaging, and delivery evidence are outside this slice",
            ],
            "delivery_artifacts": [
                "manifest JSON",
                "focused validator tests",
                "operator and limitation documentation",
            ],
        },
        "stages": _stages(),
        "receipt_refs": list(receipts),
        "task_envelope": _task_envelope(receipts),
        "measurement": {
            "status": "not_measured",
            "mechanical_edits": None,
            "llm_written_edits": None,
            "tokens": None,
            "retries": None,
            "reason": "fixture documents the accounting seam; it is not a benchmark run",
        },
        "delivery": {
            "status": "not_attempted",
            "clean_machine": False,
            "ui_exercised": False,
            "package_published": False,
        },
        "source_contracts": sorted(_SOURCE_CONTRACTS),
    }


generate_manifest = build_foundation_manifest


def _as_mapping(value: Any, label: str, errors: list[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be an object")
        return None
    return value


def validate_manifest(
    document: Mapping[str, Any], repo_root: Path = REPO_ROOT
) -> list[str]:
    """Return deterministic validation errors for a v1 manifest."""

    errors: list[str] = []
    if document.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if document.get("version") != 1:
        errors.append("version must be 1")
    if document.get("status") != FOUNDATION_STATUS:
        errors.append(f"status must be {FOUNDATION_STATUS}")

    goal_data = _as_mapping(document.get("goal_contract"), "goal_contract", errors)
    goal: GoalContract | None = None
    if goal_data is not None:
        try:
            goal = GoalContract.from_dict(goal_data)
        except (TypeError, ValueError) as exc:
            errors.append(f"goal_contract invalid: {exc}")

    envelope_data = _as_mapping(document.get("task_envelope"), "task_envelope", errors)
    envelope: TaskEnvelope | None = None
    if envelope_data is not None:
        try:
            envelope = TaskEnvelope.from_dict(dict(envelope_data))
        except (TypeError, ValueError) as exc:
            errors.append(f"task_envelope invalid: {exc}")

    stages = document.get("stages")
    if not isinstance(stages, list):
        errors.append("stages must be a list")
        stages = []
    names = [stage.get("name") for stage in stages if isinstance(stage, Mapping)]
    if tuple(names) != OPERATORS:
        errors.append(f"stages must be ordered as {OPERATORS}")
    if len(names) != len(set(names)):
        errors.append("stages must not repeat an operator")

    refs = [stage.get("receipt") for stage in stages if isinstance(stage, Mapping)]
    if document.get("receipt_refs") != refs:
        errors.append("receipt_refs must mirror stage receipt references")
    if any(
        not isinstance(ref, str) or not ref.startswith("receipt://") for ref in refs
    ):
        errors.append("every stage receipt must use the receipt:// scheme")
    if any(
        not isinstance(stage, Mapping)
        or stage.get("status") != FOUNDATION_STATUS
        or stage.get("verified") is not False
        for stage in stages
    ):
        errors.append("fixture stages must remain explicitly unverified")

    goal_refs = (
        [item.get("reference") for item in goal_data.get("evidence", [])]
        if goal_data
        else []
    )
    if goal_refs != refs:
        errors.append("goal evidence must mirror stage receipt references")
    if envelope is not None:
        if envelope.state is not TaskState.EVIDENCE_READY:
            errors.append("fixture task envelope must stop at evidence_ready")
        if list(envelope.receipts) != refs or list(envelope.evidence_refs) != refs:
            errors.append("task envelope receipts must mirror stage receipt references")

    delivery = _as_mapping(document.get("delivery"), "delivery", errors)
    if delivery is not None:
        if delivery.get("status") != "not_attempted":
            errors.append("delivery status must remain not_attempted")
        for key in ("clean_machine", "ui_exercised", "package_published"):
            if delivery.get(key) is not False:
                errors.append(
                    f"delivery.{key} must remain false in the foundation fixture"
                )

    source_contracts = document.get("source_contracts")
    if source_contracts != sorted(_SOURCE_CONTRACTS):
        errors.append("source_contracts must use the pinned local contract set")
    else:
        for relative, needles in _SOURCE_CONTRACTS.items():
            path = repo_root / relative
            if not path.is_file():
                errors.append(f"source contract missing: {relative}")
                continue
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                if needle not in text:
                    errors.append(
                        f"source contract marker missing: {relative}:{needle}"
                    )
    return errors


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _probe_command(name: str, argv: tuple[str, ...]) -> dict[str, Any]:
    """Probe a real operator without invoking a mutating operation."""

    executable = shutil.which(argv[0])
    if executable is None:
        return {
            "name": name,
            "status": "UNVERIFIED",
            "command": list(argv),
            "reason": f"{argv[0]} is not available on PATH",
        }
    try:
        result = subprocess.run(
            [executable, *argv[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": name,
            "status": "FAIL",
            "command": list(argv),
            "executable": executable,
            "reason": f"probe failed: {exc}",
        }
    output = (result.stdout or result.stderr).strip().splitlines()
    check: dict[str, Any] = {
        "name": name,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "command": list(argv),
        "executable": executable,
        "returncode": result.returncode,
    }
    if output:
        check["observed"] = output[0][:240]
    if result.returncode != 0:
        check["reason"] = "readiness probe returned non-zero"
    return check


def _probe_loop_contract(repo_root: Path) -> dict[str, Any]:
    """Check the standalone loop contract that this repository owns."""

    paths = (
        "skills/simplicio-loop/simplicio-loop/SKILL.md",
        "skills/simplicio-loop/simplicio-loop/references/bound-operators.md",
        "tools/watcher_gate.py",
    )
    missing = [relative for relative in paths if not (repo_root / relative).is_file()]
    if missing:
        return {
            "name": "loop",
            "status": "UNVERIFIED",
            "reason": "loop contract files are missing",
            "missing": missing,
        }
    bound_operators = (repo_root / paths[1]).read_text(encoding="utf-8")
    required_markers = ("simplicio-mapper", "simplicio-dev-cli")
    missing_markers = [marker for marker in required_markers if marker not in bound_operators]
    if missing_markers:
        return {
            "name": "loop",
            "status": "FAIL",
            "reason": "loop contract does not bind all required operators",
            "missing_markers": missing_markers,
        }
    return {"name": "loop", "status": "PASS", "checked": list(paths)}


def audit_integration(
    manifest_path: Path, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Return a fail-closed receipt for the real four-operator seam.

    The audit never treats fixture receipt references as execution evidence.
    Mapper, Dev CLI, and Runtime are probed by their real binaries, while the
    loop is checked against its repository-owned standalone contract. A
    missing external binary is ``UNVERIFIED`` and therefore non-success.
    """

    document = _load(manifest_path)
    errors = validate_manifest(document, repo_root=repo_root)
    checks: list[dict[str, Any]] = []
    if errors:
        checks.append({"name": "manifest", "status": "FAIL", "errors": errors})
    else:
        checks.append({"name": "manifest", "status": "PASS"})
    checks.extend(
        (
            _probe_command("mapper", ("simplicio-mapper", "--version")),
            _probe_command("dev_cli", ("simplicio-dev-cli", "--help")),
            _probe_command("runtime", ("simplicio", "--version")),
            _probe_loop_contract(repo_root),
        )
    )
    statuses = {check["status"] for check in checks}
    if "FAIL" in statuses:
        status = "FAIL"
    elif statuses != {"PASS"}:
        status = "UNVERIFIED"
    else:
        status = "PASS"
    return {
        "schema": AUDIT_SCHEMA,
        "status": status,
        "fail_closed": status != "PASS",
        "manifest": str(manifest_path),
        "checks": checks,
        "blockers": [
            check.get("reason", "manifest validation failed")
            for check in checks
            if check["status"] != "PASS"
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", metavar="PATH")
    group.add_argument("--validate", metavar="PATH")
    group.add_argument("--audit", metavar="PATH")
    args = parser.parse_args(argv)
    if args.generate:
        output = Path(args.generate)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                generate_manifest(), ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        return 0
    if args.audit:
        receipt = audit_integration(Path(args.audit))
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if receipt["status"] == "PASS" else 2
    document = _load(Path(args.validate))
    errors = validate_manifest(document)
    if errors:
        for error in errors:
            print(f"invalid manifest: {error}")
        return 1
    print(f"valid manifest: {SCHEMA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
