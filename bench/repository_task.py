"""Offline, reproducible scorer for the GAIA/repository-task evaluation lane."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

MANIFEST_SCHEMA = "simplicio.evaluation-manifest/v1"
REPORT_SCHEMA = "simplicio.evaluation-report/v1"
REQUIRED_CONFIGS = (
    "agent-current-compat",
    "agent-cache-compat",
    "agent-cache-turboquant",
    "agent-cache-speculative",
    "reference-adapter",
)
UNAVAILABLE_METRICS = ("ttft_ms", "wall_time_ms", "peak_rss_bytes", "vram_bytes")
DEFAULT_MANIFEST = Path(__file__).parents[1] / "fixtures/evaluation/gaia-repository-task.v1.json"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _required(value: Mapping[str, Any], name: str, kind: type) -> None:
    if not isinstance(value.get(name), kind):
        raise ValueError(f"{name} must be a {kind.__name__}")


def validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema must be {MANIFEST_SCHEMA}")
    configs = manifest.get("configurations")
    if not isinstance(configs, list):
        return errors + ["configurations must be a list"]
    config_ids = [c.get("id") for c in configs if isinstance(c, Mapping)]
    missing = [name for name in REQUIRED_CONFIGS if name not in config_ids]
    if missing:
        errors.append(f"missing required configurations: {', '.join(missing)}")
    if len(config_ids) != len(set(config_ids)):
        errors.append("configuration ids must be unique")
    for index, config in enumerate(configs):
        if not isinstance(config, Mapping):
            errors.append(f"configurations[{index}] must be an object")
            continue
        for field in ("id", "agent_variant", "backend", "profile"):
            if not isinstance(config.get(field), str) or not config[field].strip():
                errors.append(f"configurations[{index}].{field} must be a non-empty string")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("tasks must be a non-empty list")
    else:
        task_ids = []
        for index, task in enumerate(tasks):
            if not isinstance(task, Mapping):
                errors.append(f"tasks[{index}] must be an object")
                continue
            task_ids.append(task.get("id"))
            for field in ("id", "lane", "prompt", "expected_answer"):
                if not isinstance(task.get(field), str) or not task[field].strip():
                    errors.append(f"tasks[{index}].{field} must be a non-empty string")
        if len(task_ids) != len(set(task_ids)):
            errors.append("task ids must be unique")
    controls = manifest.get("controls")
    if not isinstance(controls, Mapping):
        errors.append("controls must be an object")
    comparisons = manifest.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        errors.append("comparisons must be a non-empty list")
    else:
        for index, comparison in enumerate(comparisons):
            if not isinstance(comparison, Mapping):
                errors.append(f"comparisons[{index}] must be an object")
                continue
            changed = comparison.get("changed_variables")
            if not isinstance(changed, list) or len(changed) != 1:
                errors.append(f"comparisons[{index}].changed_variables must contain exactly one variable")
            if comparison.get("before") not in config_ids or comparison.get("after") not in config_ids:
                errors.append(f"comparisons[{index}] references an unknown configuration")
    return sorted(set(errors))


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    return manifest


def _answer(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def score_record(record: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    config_ids = {c["id"] for c in manifest["configurations"]}
    tasks = {t["id"]: t for t in manifest["tasks"]}
    config_id = record.get("configuration_id")
    task_id = record.get("task_id")
    if config_id not in config_ids:
        raise ValueError(f"unknown configuration_id: {config_id}")
    if task_id not in tasks:
        raise ValueError(f"unknown task_id: {task_id}")
    status = record.get("status")
    if status not in {"completed", "timeout", "error"}:
        raise ValueError("status must be completed, timeout, or error")
    steps = record.get("steps")
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 0:
        raise ValueError("steps must be a non-negative integer")
    task = tasks[task_id]
    empty = not _answer(record.get("answer"))
    success = status == "completed" and not empty and _answer(record.get("answer")) == _answer(task["expected_answer"])
    evidence_complete = bool(record.get("evidence")) and record.get("validation") == "passed"
    row = {
        "configuration_id": config_id,
        "task_id": task_id,
        "repeat": record.get("repeat", 1),
        "success": success,
        "empty": empty,
        "timeout": status == "timeout",
        "steps": steps,
        "evidence_complete": evidence_complete,
        "unavailable": {
            metric: {"value": None, "evidence": f"UNVERIFIED|raw record omitted {metric}"}
            for metric in UNAVAILABLE_METRICS
        },
    }
    return row


def aggregate_records(records: list[Mapping[str, Any]], manifest: Mapping[str, Any]) -> dict[str, Any]:
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("invalid manifest: " + "; ".join(errors))
    if not records:
        raise ValueError("records must be non-empty")
    scored = [score_record(record, manifest) for record in records]
    keys = [(r["configuration_id"], r["task_id"], r["repeat"]) for r in scored]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate configuration/task/repeat record")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        grouped[row["configuration_id"]].append(row)
    configurations = {}
    for config_id in REQUIRED_CONFIGS:
        rows = grouped.get(config_id, [])
        if not rows:
            continue
        total = len(rows)
        configurations[config_id] = {
            "sample_count": total,
            "success_rate": sum(r["success"] for r in rows) / total,
            "empty_rate": sum(r["empty"] for r in rows) / total,
            "timeout_rate": sum(r["timeout"] for r in rows) / total,
            "mean_steps": sum(r["steps"] for r in rows) / total,
            "evidence_completion_rate": sum(r["evidence_complete"] for r in rows) / total,
            "metrics": {metric: None for metric in UNAVAILABLE_METRICS},
            "metric_evidence": {metric: f"UNVERIFIED|raw records omitted {metric}" for metric in UNAVAILABLE_METRICS},
        }
    single_run = len({r["repeat"] for r in scored}) == 1
    return {
        "schema": REPORT_SCHEMA,
        "manifest_sha256": hashlib.sha256(canonical_json(manifest).encode()).hexdigest(),
        "raw_records_sha256": digest(records),
        "sample_count": len(scored),
        "single_run": single_run,
        "statistical_claim": "UNVERIFIED|single-run results are not statistical proof" if single_run else "UNVERIFIED|local fixture repetitions only",
        "configurations": configurations,
        "evidence": f"MEASURED|deterministic aggregate reproduced from {len(scored)} raw records",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    aggregate.add_argument("--results", type=Path, required=True)
    aggregate.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if args.command == "validate":
        errors = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
        return 0 if not errors else 1
    manifest = load_manifest(args.manifest)
    results = json.loads(args.results.read_text(encoding="utf-8"))
    report = aggregate_records(results, manifest)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
