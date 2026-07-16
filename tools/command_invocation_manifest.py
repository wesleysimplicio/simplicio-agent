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
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
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
UNCLASSIFIED_REASON = (
    "requires turn-level runtime evidence (TurnEngine/ToolInvocationPipeline "
    "execution trace) not yet wired by the agent_tool manifest slice"
)
PASSING_STATUSES = frozenset(("pass", "not_applicable"))
VALID_STATUSES = frozenset(("pass", "fail", "not_applicable", "unknown"))
CLASS_NAME = "agent_tool"


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
    axes = [_classify_tool(name).as_dict() for name in names]
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
            "note": (
                "Partial slice of issue #398's full command-invocation-manifest. "
                "Only the agent_tool class is inventoried here, and only the four "
                "stages observable from static registry state are classified; "
                "surface_only/internal_admin/diagnostic/etc. classes and the "
                "remaining six stages are out of scope for this slice."
            ),
        },
        "axes": axes,
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
