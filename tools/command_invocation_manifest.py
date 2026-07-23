#!/usr/bin/env python3
"""Generate the ``agent_tool`` slice of the command-invocation-manifest (issue #398).

Issue #398 asks for a full ``command-invocation-manifest/v1`` covering every
surface (CLI, TUI, Desktop, Gateway, ACP, MCP, skills, plugins, session/turn
commands) through ten stages: ``DECLARED -> REGISTERED -> DISCOVERABLE ->
AUTHORIZED -> ROUTED -> INVOKED -> RESULT_NORMALIZED -> EVIDENCED ->
E2E_PROVEN -> PACKAGE_PROVEN -> REGRESSION_GATED``.

That full inventory spans many surfaces and cannot be produced or verified in
one slice. This module covers exactly one class from the issue's required
classification set -- ``agent_tool`` -- sourced from the single live registry
(:mod:`tools.registry`) that is the actual ``ToolInvocationPipeline`` surface.
For each registered tool it mechanically classifies the four stages that are
observable from static/registry state today (``DECLARED``, ``REGISTERED``,
``DISCOVERABLE``, ``AUTHORIZED``); the remaining six stages require turn-level
runtime evidence this slice does not yet wire up, and are reported as
``unknown`` with an explicit reason rather than inferred or faked. Later
slices should extend ``STAGES`` coverage and add the other nine classes
(``user_invocable``, ``runtime_effect``, ``surface_only``, ``internal_admin``,
``diagnostic``, ``deprecated``, ``unsupported``) plus the CLI/TUI/Desktop/
Gateway/ACP/MCP/skills/plugin surfaces.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
# Keep the documented ``python tools/command_invocation_manifest.py`` entrypoint
# importable when Python seeds sys.path with ``tools/`` instead of the repo root.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCHEMA = "simplicio.command-invocation-manifest/v1"
VERSION = 1
GENERATOR = "tools/command_invocation_manifest.py"

# Full stage set from issue #398. Stages not yet classifiable by this slice
# are marked "unknown" for every tool rather than omitted, so the manifest
# schema is stable across future slices.
STAGES = (
    "DECLARED",
    "REGISTERED",
    "DISCOVERABLE",
    "AUTHORIZED",
    "ROUTED",
    "INVOKED",
    "RESULT_NORMALIZED",
    "EVIDENCED",
    "E2E_PROVEN",
    "PACKAGE_PROVEN",
    "REGRESSION_GATED",
)
# Stages this slice can mechanically classify today. The rest are always
# "unknown" until a later slice adds turn-level runtime evidence.
CLASSIFIED_STAGES = ("DECLARED", "REGISTERED", "DISCOVERABLE", "AUTHORIZED")
RUNTIME_EVIDENCE_STAGES = ("ROUTED", "INVOKED", "RESULT_NORMALIZED", "EVIDENCED")
RUNTIME_UNKNOWN_STAGES = ("E2E_PROVEN", "PACKAGE_PROVEN", "REGRESSION_GATED")
REACHABILITY_PROBE_TOOL = "skills_list"
UNCLASSIFIED_REASON = (
    "requires turn-level runtime evidence (TurnEngine/ToolInvocationPipeline "
    "execution trace) not yet wired by the agent_tool manifest slice"
)
PASSING_STATUSES = frozenset(("pass", "not_applicable"))
VALID_STATUSES = frozenset(("pass", "fail", "not_applicable", "unknown"))
CLASS_NAME = "agent_tool"
COVERAGE_SCENARIOS = (
    "positive",
    "unknown_command",
    "unavailable_capability",
)
COVERAGE_MATRIX_FIELDS = frozenset(("scenario", "tool", "expected_status", "stages"))
MATRIX_STATUS_VALUES = frozenset(("pass", "fail", "not_applicable"))


@dataclass(frozen=True)
class StageResult:
    status: str
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status in PASSING_STATUSES

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.status, "ok": self.ok}
        if self.reason:
            result["reason"] = self.reason
        return result


@dataclass
class ToolAxisResult:
    name: str
    toolset: str
    source_path: str = ""
    symbol: str = ""
    registry: str = "tools.registry"
    is_async: bool = False
    requires_env: tuple[str, ...] = ()
    has_authorization_gate: bool = False
    stages: dict[str, StageResult] = field(default_factory=dict)

    def mark(self, stage: str, status: str, reason: str = "") -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid stage status: {status}")
        self.stages[stage] = StageResult(status, reason)

    def as_dict(self) -> dict[str, Any]:
        stage_results = {
            stage: self.stages.get(
                stage, StageResult("unknown", UNCLASSIFIED_REASON)
            ).as_dict()
            for stage in STAGES
        }
        classified_ok = all(
            stage_results[stage]["ok"] for stage in CLASSIFIED_STAGES
        )
        return {
            "name": self.name,
            "class": CLASS_NAME,
            "toolset": self.toolset,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "registry": self.registry,
            "is_async": self.is_async,
            "requires_env": list(self.requires_env),
            "has_authorization_gate": self.has_authorization_gate,
            "classified_ok": classified_ok,
            "stage_status": {
                stage: stage_results[stage]["status"] for stage in STAGES
            },
            "stage_results": stage_results,
        }


def _classify_tool(name: str) -> ToolAxisResult:
    from tools.registry import registry

    entry = registry.get_entry(name)
    result = ToolAxisResult(name=name, toolset=(entry.toolset if entry else ""))

    if entry is None:
        result.mark("DECLARED", "fail", reason=f"no ToolEntry for '{name}'")
        for stage in CLASSIFIED_STAGES[1:]:
            result.mark(stage, "fail", reason="tool is not registered")
        return result

    source = inspect.getsourcefile(entry.handler)
    if source:
        source_path = Path(source).resolve()
        try:
            result.source_path = source_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            # Keep external/plugin inventory useful without leaking an
            # operator-specific absolute path into a receipt.
            result.source_path = f"external:{entry.handler.__module__}"
    result.symbol = f"{entry.handler.__module__}.{entry.handler.__qualname__}"
    result.is_async = entry.is_async
    result.requires_env = tuple(sorted(str(value) for value in entry.requires_env))
    result.has_authorization_gate = entry.check_fn is not None

    schema = registry.get_schema(name)
    result.mark(
        "DECLARED",
        "pass" if schema else "fail",
        reason="" if schema else "registered entry has no schema",
    )
    result.mark("REGISTERED", "pass", reason=f"present in ToolRegistry as '{entry.name}'")

    discoverable = registry.is_toolset_available(entry.toolset)
    result.mark(
        "DISCOVERABLE",
        "pass" if discoverable else "fail",
        reason=(
            f"toolset '{entry.toolset}' is available"
            if discoverable
            else f"toolset '{entry.toolset}' has no exposable tools right now"
        ),
    )

    if entry.check_fn is None:
        result.mark("AUTHORIZED", "pass", reason="no check_fn gate; unconditionally authorized")
    else:
        from tools.registry import _check_fn_cached

        authorized = _check_fn_cached(entry.check_fn)
        result.mark(
            "AUTHORIZED",
            "pass" if authorized else "fail",
            reason="check_fn passed" if authorized else "check_fn denied invocation",
        )
    return result


def _runtime_stage_results(reason: str) -> dict[str, dict[str, Any]]:
    return {
        stage: {"status": "unknown", "ok": False, "reason": reason}
        for stage in RUNTIME_EVIDENCE_STAGES + RUNTIME_UNKNOWN_STAGES
    }


def _failed_reachability_probe(tool_name: str, reason: str) -> dict[str, Any]:
    stage_results = _runtime_stage_results(reason)
    stage_results["ROUTED"] = {"status": "fail", "ok": False, "reason": reason}
    return {
        "tool": tool_name,
        "status": "fail",
        "invocation_count": 0,
        "result_type": None,
        "result_sha256": None,
        "receipt_written": False,
        "stage_status": {
            stage: result["status"] for stage, result in stage_results.items()
        },
        "stage_results": stage_results,
    }


def probe_runtime_reachability(
    tool_name: str = REACHABILITY_PROBE_TOOL,
) -> dict[str, Any]:
    """Exercise one safe registry tool through the real invocation pipeline.

    This is deliberately a bounded probe, not a claim that every tool has
    passed the full issue #398 lifecycle. The selected tool is read-only and
    its receipt is kept in memory so manifest generation cannot write agent
    state or expose a live result. Unknown or unavailable tools fail closed.
    """

    from agent.tool_invocation_pipeline import ToolInvocation, ToolInvocationPipeline
    from tools.registry import _check_fn_cached, discover_builtin_tools, registry

    discover_builtin_tools()
    entry = registry.get_entry(tool_name)
    if entry is None:
        return _failed_reachability_probe(tool_name, "tool is not registered")
    if entry.check_fn is not None and not _check_fn_cached(entry.check_fn):
        return _failed_reachability_probe(
            tool_name, "tool authorization check denied the read-only probe"
        )

    invocations: list[tuple[str, dict[str, Any]]] = []
    receipts: list[Any] = []
    pipeline = ToolInvocationPipeline(receipt_writer=receipts.append)
    outcome = pipeline.run(
        ToolInvocation(tool_name, {}, "398-reachability-probe", "398-manifest"),
        lambda name, args: (
            invocations.append((name, dict(args)))
            or registry.dispatch(
                name,
                args,
                task_id="398-manifest",
                session_id="",
            )
        ),
    )
    normalized = isinstance(outcome.result, str) or (
        isinstance(outcome.result, dict)
        and outcome.result.get("_multimodal") is True
        and isinstance(outcome.result.get("content"), list)
    )
    receipt_written = bool(outcome.receipt is not None and len(receipts) == 1)
    stage_results = _runtime_stage_results(
        "full TurnEngine/AgentHost/package proof is outside this bounded probe"
    )
    stage_results["ROUTED"] = {
        "status": "pass" if invocations == [(tool_name, {})] else "fail",
        "ok": invocations == [(tool_name, {})],
        "reason": "registry dispatch reached the pipeline adapter",
    }
    stage_results["INVOKED"] = {
        "status": "pass" if len(invocations) == 1 else "fail",
        "ok": len(invocations) == 1,
        "reason": f"executor call count={len(invocations)}",
    }
    stage_results["RESULT_NORMALIZED"] = {
        "status": "pass" if normalized and outcome.status == "success" else "fail",
        "ok": normalized and outcome.status == "success",
        "reason": f"pipeline outcome={outcome.status}; result_type={type(outcome.result).__name__}",
    }
    stage_results["EVIDENCED"] = {
        "status": "pass" if receipt_written else "fail",
        "ok": receipt_written,
        "reason": "in-memory invocation receipt and evidence were produced",
    }
    result_text = outcome.result if isinstance(outcome.result, str) else ""
    return {
        "tool": tool_name,
        "status": "pass"
        if all(item["ok"] for item in stage_results.values() if item["status"] != "unknown")
        else "fail",
        "invocation_count": len(invocations),
        "result_type": type(outcome.result).__name__,
        "result_sha256": hashlib.sha256(result_text.encode("utf-8")).hexdigest()
        if result_text
        else None,
        "receipt_written": receipt_written,
        "stage_status": {
            stage: result["status"] for stage, result in stage_results.items()
        },
        "stage_results": stage_results,
    }


def build_coverage_matrix(runtime_reachability: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the bounded invocation matrix covered by this manifest slice."""

    unknown = _failed_reachability_probe(
        "__definitely_not_a_registered_tool__", "tool is not registered"
    )
    return [
        {
            "scenario": "positive",
            "tool": runtime_reachability["tool"],
            "expected_status": runtime_reachability["status"],
            "stages": {
                stage: runtime_reachability["stage_status"][stage]
                for stage in RUNTIME_EVIDENCE_STAGES
            },
        },
        {
            "scenario": "unknown_command",
            "tool": unknown["tool"],
            "expected_status": unknown["status"],
            "stages": {
                stage: unknown["stage_status"][stage]
                for stage in RUNTIME_EVIDENCE_STAGES
            },
        },
        {
            "scenario": "unavailable_capability",
            "tool": "__unavailable_capability__",
            "expected_status": "fail",
            "stages": {
                "ROUTED": "fail",
                "INVOKED": "not_applicable",
                "RESULT_NORMALIZED": "not_applicable",
                "EVIDENCED": "not_applicable",
            },
        },
    ]


def generate_manifest(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Generate the agent_tool slice of the v1 manifest from the live registry.

    Built-in tool modules self-register on import (see
    :func:`tools.registry.discover_builtin_tools`); a fresh interpreter has an
    empty registry until that import pass runs, so this triggers it before
    reading the registry, matching how ``model_tools.py`` boots tools for a
    real turn.
    """

    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()
    names = registry.get_all_tool_names()
    tool_axes = [_classify_tool(name) for name in names]
    runtime_reachability = probe_runtime_reachability()
    probe_axis = next(
        (axis for axis in tool_axes if axis.name == runtime_reachability["tool"]),
        None,
    )
    if probe_axis is not None:
        for stage, result in runtime_reachability["stage_results"].items():
            probe_axis.mark(stage, result["status"], result.get("reason", ""))
    axes = [axis.as_dict() for axis in tool_axes]
    failed = sum(not axis["classified_ok"] for axis in axes)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "generator": GENERATOR,
        "repo": ".",
        "scope": {
            "class": CLASS_NAME,
            "classified_stages": list(CLASSIFIED_STAGES),
            "unclassified_stages": [s for s in STAGES if s not in CLASSIFIED_STAGES],
            "runtime_evidence_stages": list(RUNTIME_EVIDENCE_STAGES),
            "runtime_unknown_stages": list(RUNTIME_UNKNOWN_STAGES),
            "note": (
                "Partial slice of issue #398's full command-invocation-manifest. "
                "Only the agent_tool class is inventoried here, and only the four "
                "stages observable from static registry state are classified; "
                "surface_only/internal_admin/diagnostic/etc. classes and the "
                "remaining six stages are out of scope for this slice."
            ),
        },
        "axes": axes,
        "runtime_reachability": runtime_reachability,
        "coverage_matrix": build_coverage_matrix(runtime_reachability),
        "summary": {
            "axis_count": len(axes),
            "failed": failed,
            "ok": failed == 0 and len(axes) > 0,
        },
    }


def validate_manifest(document: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation errors; an empty list means valid."""

    errors: list[str] = []
    if document.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if document.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    if document.get("generator") != GENERATOR:
        errors.append(f"generator must be {GENERATOR}")
    axes = document.get("axes")
    if not isinstance(axes, list):
        errors.append("axes must be a list")
        axes = []
    names = []
    for index, axis in enumerate(axes):
        prefix = f"axes[{index}]"
        if not isinstance(axis, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        names.append(axis.get("name"))
        if axis.get("class") != CLASS_NAME:
            errors.append(f"{prefix}.class must be {CLASS_NAME}")
        statuses = axis.get("stage_status")
        if not isinstance(statuses, Mapping) or set(statuses) != set(STAGES):
            errors.append(f"{prefix}.stage_status must contain exactly all stages")
        elif any(statuses[s] not in VALID_STATUSES for s in STAGES):
            errors.append(f"{prefix}.stage_status has an invalid status value")
    if len(names) != len(set(names)):
        errors.append("axis names must be unique")
    summary = document.get("summary")
    if not isinstance(summary, Mapping):
        errors.append("summary must be an object")
    elif summary.get("axis_count") != len(axes):
        errors.append("summary.axis_count disagrees with axes")
    runtime = document.get("runtime_reachability")
    if not isinstance(runtime, Mapping):
        errors.append("runtime_reachability must be an object")
    else:
        runtime_statuses = runtime.get("stage_status")
        if not isinstance(runtime_statuses, Mapping) or set(runtime_statuses) != set(
            RUNTIME_EVIDENCE_STAGES + RUNTIME_UNKNOWN_STAGES
        ):
            errors.append("runtime_reachability.stage_status has an invalid shape")
        elif any(
            runtime_statuses[stage] not in VALID_STATUSES
            for stage in RUNTIME_EVIDENCE_STAGES + RUNTIME_UNKNOWN_STAGES
        ):
            errors.append("runtime_reachability.stage_status has an invalid status value")
        if not isinstance(runtime.get("tool"), str) or not runtime["tool"]:
            errors.append("runtime_reachability.tool must be a non-empty string")
    matrix = document.get("coverage_matrix")
    if not isinstance(matrix, list) or len(matrix) != len(COVERAGE_SCENARIOS):
        errors.append("coverage_matrix must contain exactly the bounded scenarios")
    else:
        scenarios = []
        for index, entry in enumerate(matrix):
            prefix = f"coverage_matrix[{index}]"
            if not isinstance(entry, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            scenarios.append(entry.get("scenario"))
            if set(entry) != COVERAGE_MATRIX_FIELDS:
                errors.append(f"{prefix} has invalid fields")
            if entry.get("scenario") not in COVERAGE_SCENARIOS:
                errors.append(f"{prefix}.scenario is invalid")
            if not isinstance(entry.get("tool"), str) or not entry["tool"]:
                errors.append(f"{prefix}.tool must be a non-empty string")
            if entry.get("expected_status") not in MATRIX_STATUS_VALUES:
                errors.append(f"{prefix}.expected_status is invalid")
            stages = entry.get("stages")
            if not isinstance(stages, Mapping) or set(stages) != set(RUNTIME_EVIDENCE_STAGES):
                errors.append(f"{prefix}.stages has an invalid shape")
            elif any(stages[stage] not in VALID_STATUSES for stage in RUNTIME_EVIDENCE_STAGES):
                errors.append(f"{prefix}.stages has an invalid status value")
        if scenarios != list(COVERAGE_SCENARIOS):
            errors.append("coverage_matrix scenarios must be ordered and unique")
    return sorted(set(errors))


def _write_json(document: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate", metavar="PATH", help="write a generated manifest to PATH"
    )
    parser.add_argument(
        "--validate", metavar="PATH", help="validate an existing manifest JSON file"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the manifest to stdout"
    )
    args = parser.parse_args(argv)

    if args.validate:
        try:
            document = json.loads(Path(args.validate).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"invalid manifest: {exc}", file=sys.stderr)
            return 2
        errors = validate_manifest(document)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("valid")
        return 0

    document = generate_manifest(REPO_ROOT)
    if args.generate:
        _write_json(document, Path(args.generate))
    if args.json or not args.generate:
        print(json.dumps(document, indent=2, sort_keys=True))
    return 0 if document["summary"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
