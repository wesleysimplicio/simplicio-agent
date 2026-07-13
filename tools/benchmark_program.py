#!/usr/bin/env python3
"""Validate and compare a deterministic, local benchmark-program fixture.

The program is deliberately a contract and comparison gate.  It consumes
synthetic/local reports; it does not execute Hermes, OpenClaw, providers, or
network calls and therefore cannot establish real capability or latency.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = "simplicio.local-benchmark-program-manifest/v1"
REPORT_SCHEMA = "simplicio.local-benchmark-program-report/v1"
GATE_SCHEMA = "simplicio.local-benchmark-program-gate/v1"
VERSION = 1

STAGE_STATUSES = frozenset({"pass", "fail", "blocked", "skipped"})
DIRECTIONS = frozenset({"lower_is_better", "higher_is_better", "informational"})
EXECUTION_MODE = "synthetic_fixture"
NETWORK_POLICY = "disabled"

DEFAULT_MANIFEST = REPO_ROOT / "fixtures" / "bench" / "program" / "benchmark-program-manifest.v1.json"
DEFAULT_BASELINE = REPO_ROOT / "fixtures" / "bench" / "program" / "baseline.v1.json"
DEFAULT_CANDIDATE = REPO_ROOT / "fixtures" / "bench" / "program" / "candidate.v1.json"


def _mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _numeric(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        not posix.is_absolute()
        and not windows.is_absolute()
        and ".." not in (posix.parts + windows.parts)
    )


def _validate_budget(
    budget: Any, prefix: str, errors: list[str]
) -> dict[str, float]:
    if not _mapping(budget) or not budget:
        errors.append(f"{prefix} must be a non-empty object")
        return {}
    normalized: dict[str, float] = {}
    for name, value in budget.items():
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix} keys must be non-empty strings")
        if not _numeric(value) or value < 0:
            errors.append(f"{prefix}.{name} must be a non-negative number")
        else:
            normalized[name] = float(value)
    return normalized


def _stage_specs(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        stage["id"]: stage
        for stage in manifest.get("stages", [])
        if _mapping(stage) and isinstance(stage.get("id"), str)
    }


def _case_specs(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        case["id"]: case
        for case in manifest.get("cases", [])
        if _mapping(case) and isinstance(case.get("id"), str)
    }


def validate_manifest(document: Mapping[str, Any]) -> list[str]:
    """Return stable errors for the v1 local benchmark-program manifest."""

    errors: list[str] = []
    if document.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema must be {MANIFEST_SCHEMA}")
    if document.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    for field in ("program_id", "description"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            errors.append(f"{field} must be a non-empty string")

    execution = document.get("execution")
    if not _mapping(execution):
        errors.append("execution must be an object")
    else:
        if execution.get("mode") != EXECUTION_MODE:
            errors.append(f"execution.mode must be {EXECUTION_MODE}")
        if execution.get("network") != NETWORK_POLICY:
            errors.append(f"execution.network must be {NETWORK_POLICY}")
        if execution.get("capability_claims") is not False:
            errors.append("execution.capability_claims must be false")

    stages = document.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append("stages must be a non-empty list")
    else:
        stage_ids: list[str] = []
        metric_ids: set[tuple[str, str]] = set()
        for index, stage in enumerate(stages):
            prefix = f"stages[{index}]"
            if not _mapping(stage):
                errors.append(f"{prefix} must be an object")
                continue
            stage_id = stage.get("id")
            if not isinstance(stage_id, str) or not stage_id.strip():
                errors.append(f"{prefix}.id must be a non-empty string")
                continue
            stage_ids.append(stage_id)
            _validate_budget(stage.get("budgets"), f"{prefix}.budgets", errors)
            metrics = stage.get("metrics")
            if not isinstance(metrics, list) or not metrics:
                errors.append(f"{prefix}.metrics must be a non-empty list")
                continue
            for metric_index, metric in enumerate(metrics):
                metric_prefix = f"{prefix}.metrics[{metric_index}]"
                if not _mapping(metric):
                    errors.append(f"{metric_prefix} must be an object")
                    continue
                metric_id = metric.get("id")
                if not isinstance(metric_id, str) or not metric_id.strip():
                    errors.append(f"{metric_prefix}.id must be a non-empty string")
                else:
                    key = (stage_id, metric_id)
                    if key in metric_ids:
                        errors.append(f"duplicate metric: {stage_id}.{metric_id}")
                    metric_ids.add(key)
                if not isinstance(metric.get("unit"), str) or not metric["unit"].strip():
                    errors.append(f"{metric_prefix}.unit must be a non-empty string")
                if metric.get("direction") not in DIRECTIONS:
                    errors.append(
                        f"{metric_prefix}.direction must be one of {sorted(DIRECTIONS)}"
                    )
                tolerance = metric.get("tolerance")
                if not _numeric(tolerance) or tolerance < 0:
                    errors.append(f"{metric_prefix}.tolerance must be non-negative")
                budgets = stage.get("budgets")
                budget_key = metric.get("budget_key")
                if (
                    not isinstance(budget_key, str)
                    or not isinstance(budgets, Mapping)
                    or budget_key not in budgets
                ):
                    errors.append(
                        f"{metric_prefix}.budget_key must reference a declared budget"
                    )
        if len(stage_ids) != len(set(stage_ids)):
            errors.append("stage ids must be unique")

    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
    else:
        case_ids: list[str] = []
        known_stages = {stage["id"] for stage in stages or [] if _mapping(stage) and "id" in stage}
        for index, case in enumerate(cases):
            prefix = f"cases[{index}]"
            if not _mapping(case):
                errors.append(f"{prefix} must be an object")
                continue
            case_id = case.get("id")
            if not isinstance(case_id, str) or not case_id.strip():
                errors.append(f"{prefix}.id must be a non-empty string")
            else:
                case_ids.append(case_id)
            if not _safe_relative_path(case.get("fixture")):
                errors.append(f"{prefix}.fixture must be a safe relative path")
            declared_stages = case.get("stages")
            if (
                not isinstance(declared_stages, list)
                or not declared_stages
                or not all(isinstance(stage, str) and stage in known_stages for stage in declared_stages)
            ):
                errors.append(f"{prefix}.stages must reference declared stages")
        if len(case_ids) != len(set(case_ids)):
            errors.append("case ids must be unique")

    return sorted(set(errors))


def _metric_specs(stage: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        metric["id"]: metric
        for metric in stage.get("metrics", [])
        if _mapping(metric) and isinstance(metric.get("id"), str)
    }


def validate_report(
    document: Mapping[str, Any], manifest: Mapping[str, Any] | None = None
) -> list[str]:
    """Validate a local report and its stage metric measurements."""

    errors: list[str] = []
    if document.get("schema") != REPORT_SCHEMA:
        errors.append(f"schema must be {REPORT_SCHEMA}")
    if document.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    if not isinstance(document.get("manifest_id"), str) or not document["manifest_id"].strip():
        errors.append("manifest_id must be a non-empty string")
    elif manifest is not None and document["manifest_id"] != manifest.get("program_id"):
        errors.append("manifest_id must match manifest.program_id")
    if document.get("execution") != {"mode": EXECUTION_MODE, "network": NETWORK_POLICY}:
        errors.append("execution must declare synthetic_fixture mode with disabled network")

    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        return sorted(set(errors))
    known_cases = _case_specs(manifest) if manifest else {}
    stage_specs = _stage_specs(manifest) if manifest else {}
    case_ids: list[str] = []
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not _mapping(case):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"{prefix}.case_id must be a non-empty string")
            continue
        case_ids.append(case_id)
        if known_cases and case_id not in known_cases:
            errors.append(f"{prefix}.case_id is not in the manifest")
        if case.get("status") not in STAGE_STATUSES:
            errors.append(f"{prefix}.status must be one of {sorted(STAGE_STATUSES)}")
        stages = case.get("stages")
        if not isinstance(stages, list) or not stages:
            errors.append(f"{prefix}.stages must be a non-empty list")
            continue
        stage_ids: list[str] = []
        expected_ids = known_cases.get(case_id, {}).get("stages", [])
        for stage_index, stage in enumerate(stages):
            stage_prefix = f"{prefix}.stages[{stage_index}]"
            if not _mapping(stage):
                errors.append(f"{stage_prefix} must be an object")
                continue
            stage_id = stage.get("stage_id")
            if not isinstance(stage_id, str) or not stage_id.strip():
                errors.append(f"{stage_prefix}.stage_id must be a non-empty string")
                continue
            stage_ids.append(stage_id)
            if expected_ids and stage_id not in expected_ids:
                errors.append(f"{stage_prefix}.stage_id is not declared for the case")
            if stage.get("status") not in STAGE_STATUSES:
                errors.append(
                    f"{stage_prefix}.status must be one of {sorted(STAGE_STATUSES)}"
                )
            metrics = stage.get("metrics")
            if not isinstance(metrics, Mapping):
                errors.append(f"{stage_prefix}.metrics must be an object")
                continue
            specs = _metric_specs(stage_specs.get(stage_id, {}))
            if specs and set(metrics) != set(specs):
                errors.append(f"{stage_prefix}.metrics must match manifest metrics")
            for metric_id, value in metrics.items():
                if specs and metric_id not in specs:
                    errors.append(f"{stage_prefix}.metrics.{metric_id} is not declared")
                if not _numeric(value) or value < 0:
                    errors.append(f"{stage_prefix}.metrics.{metric_id} must be non-negative numeric")
        if len(stage_ids) != len(set(stage_ids)):
            errors.append(f"{prefix}.stage ids must be unique")
        if expected_ids and set(stage_ids) != set(expected_ids):
            errors.append(f"{prefix}.stages must cover the case's declared stages")
    if len(case_ids) != len(set(case_ids)):
        errors.append("report case ids must be unique")
    if known_cases and set(case_ids) != set(known_cases):
        errors.append("report cases must cover every manifest case")
    return sorted(set(errors))


def _report_rows(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        case["case_id"]: case
        for case in report.get("cases", [])
        if _mapping(case) and isinstance(case.get("case_id"), str)
    }


def _stage_rows(case: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        stage["stage_id"]: stage
        for stage in case.get("stages", [])
        if _mapping(stage) and isinstance(stage.get("stage_id"), str)
    }


def _is_regression(direction: str, baseline: float, candidate: float, tolerance: float) -> bool:
    if direction == "informational":
        return False
    if baseline == 0:
        return candidate > 0 if direction == "lower_is_better" else candidate < 0
    change = (candidate - baseline) / abs(baseline)
    if direction == "lower_is_better":
        return change > tolerance
    return change < -tolerance


def compare_reports(
    manifest: Mapping[str, Any],
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare two local reports and fail closed on budget/regression drift."""

    manifest_errors = validate_manifest(manifest)
    baseline_errors = validate_report(baseline, manifest)
    candidate_errors = validate_report(candidate, manifest)
    comparisons: list[dict[str, Any]] = []
    budget_violations: list[str] = []
    regressions: list[str] = []
    if not manifest_errors and not baseline_errors and not candidate_errors:
        for case_id in sorted(_case_specs(manifest)):
            baseline_stages = _stage_rows(_report_rows(baseline)[case_id])
            candidate_stages = _stage_rows(_report_rows(candidate)[case_id])
            case_stage_ids = _case_specs(manifest)[case_id]["stages"]
            for stage_id in sorted(case_stage_ids):
                stage_spec = _stage_specs(manifest)[stage_id]
                baseline_stage = baseline_stages[stage_id]
                candidate_stage = candidate_stages[stage_id]
                candidate_status = candidate_stage["status"]
                if candidate_status != "pass":
                    regressions.append(f"{case_id}.{stage_id}.status={candidate_status}")
                for metric_id in sorted(_metric_specs(stage_spec)):
                    metric_spec = _metric_specs(stage_spec)[metric_id]
                    before = float(baseline_stage["metrics"][metric_id])
                    after = float(candidate_stage["metrics"][metric_id])
                    delta = after - before
                    percent_change = None if before == 0 else delta / abs(before)
                    path = f"{case_id}.{stage_id}.{metric_id}"
                    budget = float(stage_spec["budgets"][metric_spec["budget_key"]])
                    over_budget = after > budget
                    if over_budget:
                        budget_violations.append(f"{path}={after:g}>{budget:g}")
                    regression = _is_regression(
                        metric_spec["direction"],
                        before,
                        after,
                        float(metric_spec["tolerance"]),
                    )
                    if regression:
                        regressions.append(path)
                    comparisons.append(
                        {
                            "case_id": case_id,
                            "stage_id": stage_id,
                            "metric_id": metric_id,
                            "baseline": before,
                            "candidate": after,
                            "delta": delta,
                            "percent_change": percent_change,
                            "tolerance": metric_spec["tolerance"],
                            "budget": budget,
                            "over_budget": over_budget,
                            "regression": regression,
                        }
                    )
    errors = sorted(set(manifest_errors + baseline_errors + candidate_errors))
    blocked = bool(errors or budget_violations or regressions)
    return {
        "schema": GATE_SCHEMA,
        "version": VERSION,
        "manifest_id": manifest.get("program_id"),
        "baseline_id": baseline.get("report_id"),
        "candidate_id": candidate.get("report_id"),
        "status": "blocked" if blocked else "pass",
        "manifest_errors": manifest_errors,
        "baseline_errors": baseline_errors,
        "candidate_errors": candidate_errors,
        "budget_violations": sorted(budget_violations),
        "regressions": sorted(regressions),
        "comparisons": comparisons,
        "summary": {
            "metric_count": len(comparisons),
            "regression_count": len(regressions),
            "budget_violation_count": len(budget_violations),
        },
        "limitations": [
            "Reports are synthetic/local fixtures and use no network measurements.",
            "This gate does not establish Hermes or OpenClaw capability.",
            "Metric values are comparable only within this versioned fixture contract.",
        ],
    }


def evaluate_gate(
    manifest: Mapping[str, Any],
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Compatibility name for callers that treat comparison as a gate."""

    return compare_reports(manifest, baseline, candidate)


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not _mapping(value):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _emit(value: Mapping[str, Any], output: Path | None, as_json: bool) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if as_json or output is None:
        sys.stdout.write(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-manifest")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    validate.add_argument("--json", action="store_true")
    compare = subparsers.add_parser("compare")
    compare.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    compare.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    compare.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    compare.add_argument("--output", type=Path)
    compare.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = _read_json(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.command == "validate-manifest":
        errors = validate_manifest(manifest)
        result = {
            "schema": MANIFEST_SCHEMA,
            "version": VERSION,
            "valid": not errors,
            "errors": errors,
        }
        _emit(result, None, args.json)
        return 0 if not errors else 1

    try:
        baseline = _read_json(args.baseline)
        candidate = _read_json(args.candidate)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = compare_reports(manifest, baseline, candidate)
    _emit(result, args.output, args.json)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
