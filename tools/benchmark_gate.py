#!/usr/bin/env python3
"""Validate the versioned capability benchmark contract and release gate.

This module is intentionally an offline contract gate.  It validates task
declarations and supplied result receipts; it does not claim that a domain was
executed merely because a task exists in the manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

MANIFEST_SCHEMA = "simplicio.capability-benchmark-manifest/v1"
REPORT_SCHEMA = "simplicio.capability-benchmark-report/v1"
GATE_SCHEMA = "simplicio.capability-release-gate/v1"
VERSION = 1

REQUIRED_SUITES = frozenset({
    "desktop",
    "browser",
    "coding",
    "media",
    "office",
    "mobile",
    "persistent-run",
})
EVIDENCE_KINDS = frozenset({"measured", "replay", "benchmark", "estimated"})
STATUSES = frozenset({"pass", "fail", "blocked", "skipped"})
RISK_MODES = frozenset({"read_only", "guarded", "destructive"})
ARTIFACT_KINDS = frozenset({"log", "screenshot", "video", "audio", "trace", "document"})
BLOCKED_REASONS = frozenset({
    "missing_capability",
    "missing_permission",
    "missing_secret",
})
SHA256 = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bench"
    / "capability"
    / "capability-manifest.v1.json"
)


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _strings(
    value: Any, field: str, errors: list[str], *, required: bool = True
) -> list[str]:
    if value is None and not required:
        return []
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        errors.append(f"{field} must be a non-empty list of strings")
        return []
    return list(value)


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


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _validate_task(task: Any, prefix: str, errors: list[str]) -> str | None:
    if not _is_mapping(task):
        errors.append(f"{prefix} must be an object")
        return None
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        errors.append(f"{prefix}.id must be a non-empty string")
        task_id = None
    for field in ("setup", "constraints", "expected_artifacts"):
        _strings(task.get(field), f"{prefix}.{field}", errors)
    for field in ("goal", "verifier"):
        if not isinstance(task.get(field), str) or not task[field].strip():
            errors.append(f"{prefix}.{field} must be a non-empty string")
    if task.get("risk_mode") not in RISK_MODES:
        errors.append(f"{prefix}.risk_mode must be one of {sorted(RISK_MODES)}")
    timeout = task.get("timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        errors.append(f"{prefix}.timeout_seconds must be a positive integer")
    if not isinstance(task.get("smoke"), bool):
        errors.append(f"{prefix}.smoke must be a boolean")
    requirements = task.get("requirements", [])
    if requirements is not None:
        _strings(requirements, f"{prefix}.requirements", errors, required=False)
    return task_id


def validate_manifest(document: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for a v1 task manifest."""

    errors: list[str] = []
    if document.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema must be {MANIFEST_SCHEMA}")
    if document.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    if (
        not isinstance(document.get("manifest_id"), str)
        or not document["manifest_id"].strip()
    ):
        errors.append("manifest_id must be a non-empty string")
    suites = document.get("suites")
    if not isinstance(suites, list) or not suites:
        errors.append("suites must be a non-empty list")
        return sorted(set(errors))

    suite_ids: list[str] = []
    task_ids: list[str] = []
    for suite_index, suite in enumerate(suites):
        prefix = f"suites[{suite_index}]"
        if not _is_mapping(suite):
            errors.append(f"{prefix} must be an object")
            continue
        suite_id = suite.get("id")
        if not isinstance(suite_id, str) or not suite_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        else:
            suite_ids.append(suite_id)
        if suite.get("domain") != suite_id:
            errors.append(f"{prefix}.domain must equal {prefix}.id")
        tasks = suite.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"{prefix}.tasks must be a non-empty list")
            continue
        for task_index, task in enumerate(tasks):
            task_id = _validate_task(task, f"{prefix}.tasks[{task_index}]", errors)
            if task_id:
                task_ids.append(task_id)

    if len(suite_ids) != len(set(suite_ids)):
        errors.append("suite ids must be unique")
    if len(task_ids) != len(set(task_ids)):
        errors.append("task ids must be unique")
    missing = sorted(REQUIRED_SUITES - set(suite_ids))
    if missing:
        errors.append("missing required suites: " + ",".join(missing))
    return sorted(set(errors))


def _validate_metric(metric: Any, prefix: str, errors: list[str]) -> None:
    if not _is_mapping(metric):
        errors.append(f"{prefix} must be an object")
        return
    value = metric.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{prefix}.value must be numeric")
    if not isinstance(metric.get("unit"), str) or not metric["unit"].strip():
        errors.append(f"{prefix}.unit must be a non-empty string")
    if metric.get("evidence_kind") not in EVIDENCE_KINDS:
        errors.append(f"{prefix}.evidence_kind must be one of {sorted(EVIDENCE_KINDS)}")
    if not isinstance(metric.get("source"), str) or not metric["source"].strip():
        errors.append(f"{prefix}.source must be a non-empty string")


def _validate_artifact(artifact: Any, prefix: str, errors: list[str]) -> None:
    if not _is_mapping(artifact):
        errors.append(f"{prefix} must be an object")
        return
    if artifact.get("kind") not in ARTIFACT_KINDS:
        errors.append(f"{prefix}.kind must be one of {sorted(ARTIFACT_KINDS)}")
    if not _safe_relative_path(artifact.get("path")):
        errors.append(f"{prefix}.path must be a safe relative path")
    if not _sha256(artifact.get("sha256")):
        errors.append(f"{prefix}.sha256 must be a lowercase SHA-256 digest")
    if artifact.get("sanitized") is not True:
        errors.append(f"{prefix}.sanitized must be true")
    redactions = artifact.get("redactions", [])
    if redactions is not None:
        _strings(redactions, f"{prefix}.redactions", errors, required=False)


def _manifest_tasks(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        task["id"]: task
        for suite in document.get("suites", [])
        if _is_mapping(suite)
        for task in suite.get("tasks", [])
        if _is_mapping(task) and isinstance(task.get("id"), str)
    }


def validate_report(
    document: Mapping[str, Any], manifest: Mapping[str, Any] | None = None
) -> list[str]:
    """Validate a result receipt without treating estimates as execution proof."""

    errors: list[str] = []
    if document.get("schema") != REPORT_SCHEMA:
        errors.append(f"schema must be {REPORT_SCHEMA}")
    if document.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    if (
        not isinstance(document.get("manifest_id"), str)
        or not document["manifest_id"].strip()
    ):
        errors.append("manifest_id must be a non-empty string")
    elif manifest is not None and document["manifest_id"] != manifest.get(
        "manifest_id"
    ):
        errors.append("manifest_id must match the manifest")
    if document.get("run_mode") not in {"smoke", "full", "nightly", "release"}:
        errors.append("run_mode must be smoke, full, nightly, or release")
    runner = document.get("runner")
    if not _is_mapping(runner):
        errors.append(
            "runner must be an object with labeled platform, os, and hardware"
        )
    else:
        for field in ("platform", "os", "hardware"):
            if not isinstance(runner.get(field), str) or not runner[field].strip():
                errors.append(f"runner.{field} must be a non-empty string")
    rows = document.get("tasks")
    if not isinstance(rows, list) or not rows:
        errors.append("tasks must be a non-empty list")
        return sorted(set(errors))

    known = _manifest_tasks(manifest) if manifest else {}
    row_ids: list[str] = []
    for index, row in enumerate(rows):
        prefix = f"tasks[{index}]"
        if not _is_mapping(row):
            errors.append(f"{prefix} must be an object")
            continue
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(f"{prefix}.task_id must be a non-empty string")
        else:
            row_ids.append(task_id)
            if known and task_id not in known:
                errors.append(f"{prefix}.task_id is not in the manifest")
        if row.get("status") not in STATUSES:
            errors.append(f"{prefix}.status must be one of {sorted(STATUSES)}")
        if row.get("evidence_kind") not in EVIDENCE_KINDS:
            errors.append(
                f"{prefix}.evidence_kind must be one of {sorted(EVIDENCE_KINDS)}"
            )
        metrics = row.get("metrics")
        if not _is_mapping(metrics) or "task_success" not in metrics:
            errors.append(f"{prefix}.metrics.task_success is required")
        elif _is_mapping(metrics):
            for name, metric in metrics.items():
                _validate_metric(metric, f"{prefix}.metrics.{name}", errors)
        artifacts = row.get("artifacts", [])
        if not isinstance(artifacts, list):
            errors.append(f"{prefix}.artifacts must be a list")
        else:
            for artifact_index, artifact in enumerate(artifacts):
                _validate_artifact(
                    artifact, f"{prefix}.artifacts[{artifact_index}]", errors
                )
        if row.get("status") in {"fail", "blocked"} and not artifacts:
            errors.append(
                f"{prefix}.artifacts must be non-empty for {row['status']} results"
            )
        if (
            row.get("status") == "blocked"
            and row.get("blocked_reason") not in BLOCKED_REASONS
        ):
            errors.append(
                f"{prefix}.blocked_reason must be one of {sorted(BLOCKED_REASONS)}"
            )
    if len(row_ids) != len(set(row_ids)):
        errors.append("report task ids must be unique")
    return sorted(set(errors))


def _task_success(row: Mapping[str, Any]) -> tuple[bool, str]:
    metric = row.get("metrics", {}).get("task_success", {})
    measured = metric.get("evidence_kind") == "measured"
    return measured and metric.get("value") == 1, metric.get("evidence_kind", "missing")


def evaluate_gate(
    manifest: Mapping[str, Any], report: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate smoke and release promotion without inventing domain results."""

    manifest_errors = validate_manifest(manifest)
    report_errors = validate_report(report, manifest)
    tasks = _manifest_tasks(manifest)
    rows = {
        row.get("task_id"): row
        for row in report.get("tasks", [])
        if _is_mapping(row) and isinstance(row.get("task_id"), str)
    }
    smoke_ids = sorted(
        task_id for task_id, task in tasks.items() if task.get("smoke") is True
    )
    expected_ids = (
        set(tasks)
        if report.get("run_mode") in {"full", "nightly", "release"}
        else set(smoke_ids)
    )
    missing = sorted(expected_ids - set(rows))
    failures = sorted(
        task_id
        for task_id in expected_ids
        if task_id in rows and rows[task_id].get("status") == "fail"
    )
    blocked = sorted(
        task_id
        for task_id in expected_ids
        if task_id in rows and rows[task_id].get("status") == "blocked"
    )
    unmeasured = sorted(
        task_id
        for task_id in expected_ids
        if task_id in rows
        and rows[task_id].get("status") == "pass"
        and not _task_success(rows[task_id])[0]
    )
    passed = sorted(
        task_id
        for task_id in expected_ids
        if task_id in rows
        and rows[task_id].get("status") == "pass"
        and task_id not in unmeasured
    )
    estimated = sum(
        1
        for row in rows.values()
        if _is_mapping(row.get("metrics"))
        for metric in row["metrics"].values()
        if _is_mapping(metric) and metric.get("evidence_kind") == "estimated"
    )
    measured = sum(
        1
        for row in rows.values()
        if _is_mapping(row.get("metrics"))
        for metric in row["metrics"].values()
        if _is_mapping(metric) and metric.get("evidence_kind") == "measured"
    )
    smoke_ready = (
        not manifest_errors
        and not report_errors
        and not missing
        and not failures
        and not blocked
        and not unmeasured
    )
    full_matrix = report.get("run_mode") in {
        "full",
        "nightly",
        "release",
    } and expected_ids == set(tasks)
    release_ready = smoke_ready and full_matrix
    reasons: list[str] = []
    if manifest_errors:
        reasons.append("invalid_manifest")
    if report_errors:
        reasons.append("invalid_report")
    if missing:
        reasons.append("missing_task_results")
    if failures:
        reasons.append("failed_tasks")
    if blocked:
        reasons.append("blocked_tasks")
    if unmeasured:
        reasons.append("task_success_is_not_measured")
    if not full_matrix:
        reasons.append("full_matrix_not_executed")
    return {
        "schema": GATE_SCHEMA,
        "version": VERSION,
        "manifest_id": manifest.get("manifest_id"),
        "run_mode": report.get("run_mode"),
        "smoke_task_count": len(smoke_ids),
        "expected_task_count": len(expected_ids),
        "observed_task_count": len(rows),
        "passed_task_ids": passed,
        "failed_task_ids": failures,
        "blocked_task_ids": blocked,
        "missing_task_ids": missing,
        "unmeasured_task_ids": unmeasured,
        "measured_metric_count": measured,
        "estimated_metric_count": estimated,
        "smoke_ready": smoke_ready,
        "release_ready": release_ready,
        "status": "pass"
        if release_ready
        else ("smoke_pass" if smoke_ready else "blocked"),
        "reasons": sorted(set(reasons)),
        "manifest_errors": manifest_errors,
        "report_errors": report_errors,
        "limitations": [
            "A manifest entry is a declaration, not proof that its domain was executed.",
            "Estimated, replay, and benchmark metrics are retained but cannot satisfy measured task_success.",
            "Release promotion requires a full report with measured task_success for every manifest task.",
        ],
    }


def contract_smoke(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Run the offline PR smoke: validate declarations, execute no capability task."""

    errors = validate_manifest(manifest)
    return {
        "schema": GATE_SCHEMA,
        "version": VERSION,
        "manifest_id": manifest.get("manifest_id"),
        "status": "contract_pass" if not errors else "blocked",
        "release_ready": False,
        "smoke_ready": False,
        "executed_task_count": 0,
        "manifest_errors": errors,
        "claims": [],
        "limitations": [
            "No desktop, browser, coding, media, office, mobile, or persistent-run capability was executed.",
            "This output proves only that the versioned manifest contract is valid.",
        ],
    }


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not _is_mapping(value):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _emit(value: Mapping[str, Any], output: Path | None, as_json: bool) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output:
        output.write_text(rendered, encoding="utf-8")
    if as_json or not output:
        sys.stdout.write(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-manifest")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    validate.add_argument("--json", action="store_true")
    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    smoke.add_argument("--report", type=Path)
    smoke.add_argument("--output", type=Path)
    smoke.add_argument("--json", action="store_true")
    gate = subparsers.add_parser("gate")
    gate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    gate.add_argument("--report", type=Path, required=True)
    gate.add_argument("--output", type=Path)
    gate.add_argument("--json", action="store_true")
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
    if args.command == "smoke" and not args.report:
        result = contract_smoke(manifest)
        _emit(result, args.output, args.json)
        return 0 if result["status"] == "contract_pass" else 1
    if not args.report:
        parser.error("--report is required for the gate")
    try:
        report = _read_json(args.report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = evaluate_gate(manifest, report)
    _emit(result, args.output, args.json)
    if args.command == "smoke":
        return 0 if result["smoke_ready"] else 1
    return 0 if result["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
