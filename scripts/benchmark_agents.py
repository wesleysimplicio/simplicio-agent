#!/usr/bin/env python3
"""Run a reproducible, runtime-supervised four-agent benchmark.

The harness is intentionally an adapter boundary.  It does not implement an
agent, tokenizer, or provider and it never turns a missing measurement into a
zero.  Each configured agent must emit JSONL lifecycle events while the
configured Simplicio Runtime command supervises it::

    {"event": "startup_ready", "elapsed_ms": 12.4}
    {"event": "ttft", "elapsed_ms": 55.1}
    {"event": "roundtrip", "duration_ms": 4.2}
    {"event": "watcher_gate", "duration_ms": 1.1}
    {"event": "kernel_bindings", "duration_ms": 0.8}
    {"event": "handles_lazy", "duration_ms": 0.7}
    {"event": "task_complete", "tokens": 123, "tokenizer": "runtime#2775"}

The parent process measures task wall time.  Stage metrics are accepted only
from explicit events; inferring TTFT or tokens from process duration/output is
deliberately forbidden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = "simplicio.agent-benchmark-manifest/v1"
REPORT_SCHEMA = "simplicio.agent-benchmark-report/v1"
EVENT_SCHEMA = "simplicio.agent-benchmark-event/v1"
VERSION = 1

REQUIRED_AGENTS = frozenset({
    "simplicio-agent",
    "hermes-agent",
    "hermes-turbo-agent",
    "openclaw",
})
METRIC_UNITS = {
    "startup_ms": "milliseconds",
    "ttft_ms": "milliseconds",
    "roundtrip_ms": "milliseconds",
    "watcher_gate_ms": "milliseconds",
    "kernel_bindings_ms": "milliseconds",
    "handles_lazy_ms": "milliseconds",
    "task_ms": "milliseconds",
    "tokens": "tokens",
}
METRIC_EVENTS = {
    "startup_ms": ("startup_ready", "elapsed_ms"),
    "ttft_ms": ("ttft", "elapsed_ms"),
    "roundtrip_ms": ("roundtrip", "duration_ms"),
    "watcher_gate_ms": ("watcher_gate", "duration_ms"),
    "kernel_bindings_ms": ("kernel_bindings", "duration_ms"),
    "handles_lazy_ms": ("handles_lazy", "duration_ms"),
}
BUDGET_KEYS = tuple(f"{metric}_p95" for metric in METRIC_UNITS if metric != "tokens")
NULL_REASON_RUNTIME = "runtime_unavailable"


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _non_empty_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _null(reason: str) -> dict[str, Any]:
    return {"value": None, "reason": reason}


def _value(value: Any, *, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "reason": reason} if reason else {"value": value}


def validate_manifest(document: Mapping[str, Any]) -> list[str]:
    """Validate the manifest without checking whether external commands exist."""

    errors: list[str] = []
    if document.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema must be {MANIFEST_SCHEMA}")
    if document.get("version") != VERSION:
        errors.append(f"version must be {VERSION}")
    for field in ("benchmark_id", "description"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            errors.append(f"{field} must be a non-empty string")

    runtime = document.get("runtime")
    if not isinstance(runtime, Mapping):
        errors.append("runtime must be an object")
    else:
        if not _non_empty_strings(runtime.get("command")):
            errors.append("runtime.command must be a non-empty argv list")
        else:
            executable = Path(runtime["command"][0]).name
            if (
                executable not in {"simplicio", "simplicio-runtime"}
                and runtime.get("test_only") is not True
            ):
                errors.append(
                    "runtime.command must invoke simplicio or simplicio-runtime"
                )
            if "--" not in runtime["command"]:
                errors.append(
                    "runtime.command must contain -- before the supervised command"
                )
        if runtime.get("required") is not True:
            errors.append("runtime.required must be true")

    tokenizer = document.get("tokenizer")
    if not isinstance(tokenizer, Mapping):
        errors.append("tokenizer must be an object")
    elif not isinstance(tokenizer.get("label"), str) or not tokenizer["label"].strip():
        errors.append("tokenizer.label must be a non-empty string")

    repeats = document.get("best_of_n")
    warmups = document.get("warmups")
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        errors.append("best_of_n must be a positive integer")
    if not isinstance(warmups, int) or isinstance(warmups, bool) or warmups < 0:
        errors.append("warmups must be a non-negative integer")

    budgets = document.get("budgets_ms")
    if not isinstance(budgets, Mapping):
        errors.append("budgets_ms must be an object")
    else:
        for key in BUDGET_KEYS:
            value = budgets.get(key)
            if not _is_number(value) or value < 0:
                errors.append(f"budgets_ms.{key} must be a non-negative number")

    agents = document.get("agents")
    if not isinstance(agents, list) or not agents:
        errors.append("agents must be a non-empty list")
    else:
        ids: list[str] = []
        for index, agent in enumerate(agents):
            prefix = f"agents[{index}]"
            if not isinstance(agent, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            agent_id = agent.get("id")
            if not isinstance(agent_id, str) or not agent_id.strip():
                errors.append(f"{prefix}.id must be a non-empty string")
            else:
                ids.append(agent_id)
            if not _non_empty_strings(agent.get("command")):
                errors.append(f"{prefix}.command must be a non-empty argv list")
        if len(ids) != len(set(ids)):
            errors.append("agent ids must be unique")
        if set(ids) != REQUIRED_AGENTS:
            errors.append("agents must contain exactly the four required agent ids")

    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("tasks must be a non-empty list")
    else:
        ids = []
        for index, task in enumerate(tasks):
            prefix = f"tasks[{index}]"
            if not isinstance(task, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            task_id = task.get("id")
            if not isinstance(task_id, str) or not task_id.strip():
                errors.append(f"{prefix}.id must be a non-empty string")
            else:
                ids.append(task_id)
            args = task.get("args", [])
            if not isinstance(args, list) or not all(
                isinstance(item, str) for item in args
            ):
                errors.append(f"{prefix}.args must be a list of strings")
            timeout = task.get("timeout_s")
            if (
                not isinstance(timeout, (int, float))
                or isinstance(timeout, bool)
                or timeout <= 0
            ):
                errors.append(f"{prefix}.timeout_s must be positive")
        if len(ids) != len(set(ids)):
            errors.append("task ids must be unique")
    return sorted(set(errors))


def _digest_command(command: Sequence[str]) -> str:
    payload = json.dumps(list(command), ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event_metrics(
    events: Sequence[Mapping[str, Any]], tokenizer_label: str
) -> dict[str, dict[str, Any]]:
    metrics = {
        metric: _null(f"event_missing:{event}")
        for metric, (event, _) in METRIC_EVENTS.items()
    }
    metrics["tokens"] = _null("event_missing:task_complete.tokens")
    token_reason = "event_missing:task_complete.tokenizer"
    for event in events:
        name = event.get("event")
        if name == "task_complete":
            tokens = event.get("tokens")
            label = event.get("tokenizer")
            if not _is_number(tokens) or tokens < 0:
                metrics["tokens"] = _null("invalid:task_complete.tokens")
            elif label != tokenizer_label:
                metrics["tokens"] = _null(
                    f"tokenizer_mismatch:expected={tokenizer_label}:observed={label or 'missing'}"
                )
            else:
                metrics["tokens"] = _value(tokens)
            token_reason = ""
        for metric, (expected_event, field) in METRIC_EVENTS.items():
            if name != expected_event or metrics[metric].get("value") is not None:
                continue
            value = event.get(field)
            if _is_number(value) and value >= 0:
                metrics[metric] = _value(value)
            else:
                metrics[metric] = _null(f"invalid:{expected_event}.{field}")
    if token_reason and metrics["tokens"].get("value") is None:
        metrics["tokens"] = _null(token_reason)
    return metrics


def _parse_events(output: str) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    invalid = 0
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("event"), str):
            invalid += 1
            continue
        if value.get("schema") not in (None, EVENT_SCHEMA):
            invalid += 1
            continue
        events.append(value)
    return events, invalid


def _missing_metrics(reason: str) -> dict[str, dict[str, Any]]:
    return {metric: _null(reason) for metric in METRIC_UNITS}


def run_one(
    manifest: Mapping[str, Any],
    agent: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    run_number: int,
    warmup: bool,
) -> dict[str, Any]:
    """Run one task through the configured runtime and return one receipt."""

    runtime = manifest["runtime"]
    tokenizer_label = manifest["tokenizer"]["label"]
    command = (
        list(runtime["command"]) + list(agent["command"]) + list(task.get("args", []))
    )
    base = {
        "agent": agent["id"],
        "task_id": task["id"],
        "run": run_number,
        "warmup": warmup,
        "command_sha256": _digest_command(command),
        "runtime_command_sha256": _digest_command(runtime["command"]),
        "metrics": {},
    }
    if not agent["command"]:
        base.update(status="blocked", reason="agent_command_missing", exit_code=None)
        base["metrics"] = _missing_metrics("agent_command_missing")
        return base

    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except (FileNotFoundError, OSError) as exc:
        base.update(
            status="blocked",
            reason=f"{NULL_REASON_RUNTIME}:{type(exc).__name__}:{exc}",
            exit_code=None,
        )
        base["metrics"] = _missing_metrics(base["reason"])
        return base

    try:
        output, _ = process.communicate(timeout=float(task["timeout_s"]))
        timed_out = False
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        timed_out = True
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    events, invalid_events = _parse_events(output)
    metrics = _event_metrics(events, tokenizer_label)
    if not timed_out and process.returncode == int(task.get("expected_exit_code", 0)):
        metrics["task_ms"] = _value(elapsed_ms)
        status = (
            "measured"
            if all(metric["value"] is not None for metric in metrics.values())
            else "partial"
        )
        reason = None
    elif timed_out:
        metrics["task_ms"] = _null("timeout")
        status = "failed"
        reason = "timeout"
    else:
        metrics["task_ms"] = _null(f"exit_code:{process.returncode}")
        status = "failed"
        reason = f"exit_code:{process.returncode}"
    base.update(
        status=status,
        reason=reason,
        exit_code=process.returncode,
        elapsed_ms=elapsed_ms,
        event_count=len(events),
        invalid_event_count=invalid_events,
        metrics=metrics,
    )
    return base


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile / 100.0) - 1)
    return ordered[index]


def aggregate_runs(
    manifest: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Aggregate non-warmup samples with nearest-rank p95 semantics."""

    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for run in runs:
        if not run.get("warmup"):
            groups.setdefault((run["agent"], run["task_id"]), []).append(run)
    rows: list[dict[str, Any]] = []
    for (agent, task_id), samples in sorted(groups.items()):
        metrics: dict[str, dict[str, Any]] = {}
        for metric, unit in METRIC_UNITS.items():
            values = [
                float(sample["metrics"][metric]["value"])
                for sample in samples
                if sample.get("status") in {"measured", "partial"}
                and sample.get("metrics", {}).get(metric, {}).get("value") is not None
            ]
            if values:
                metrics[metric] = _with_unit(_percentile(values, 95), unit=unit)
                metrics[metric]["samples"] = len(values)
            else:
                reasons = sorted({
                    str(
                        sample
                        .get("metrics", {})
                        .get(metric, {})
                        .get("reason", "missing")
                    )
                    for sample in samples
                })
                metrics[metric] = _null(";".join(reasons))
                metrics[metric]["unit"] = unit
        rows.append({
            "agent": agent,
            "task_id": task_id,
            "sample_count": len(samples),
            "statuses": sorted({str(sample.get("status")) for sample in samples}),
            "metrics": metrics,
        })
    return rows


def _with_unit(value: Any, *, unit: str) -> dict[str, Any]:
    result = _value(value)
    result["unit"] = unit
    return result


def _budget_gate(
    manifest: Mapping[str, Any], aggregates: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    budgets = manifest["budgets_ms"]
    violations: list[str] = []
    missing: list[str] = []
    for row in aggregates:
        for metric in METRIC_UNITS:
            if metric == "tokens":
                continue
            key = f"{metric}_p95"
            measurement = row["metrics"][metric]
            value = measurement.get("value")
            path = f"{row['agent']}.{row['task_id']}.{metric}"
            if value is None:
                missing.append(f"{path}:{measurement.get('reason', 'missing')}")
            elif value > budgets[key]:
                violations.append(f"{path}={value:g}>{budgets[key]:g}")
    return {
        "status": "blocked" if violations or missing else "pass",
        "budget_violations": sorted(violations),
        "missing_metrics": sorted(missing),
    }


def compare_reports(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerance: float = 0.2,
) -> dict[str, Any]:
    """Compare measured p95 values and fail closed on missing evidence."""

    baseline_rows = {
        (row["agent"], row["task_id"]): row for row in baseline.get("aggregates", [])
    }
    candidate_rows = {
        (row["agent"], row["task_id"]): row for row in candidate.get("aggregates", [])
    }
    regressions: list[str] = []
    missing: list[str] = []
    for key in sorted(set(baseline_rows) | set(candidate_rows)):
        before = baseline_rows.get(key)
        after = candidate_rows.get(key)
        if before is None or after is None:
            missing.append(f"{key[0]}.{key[1]}:row_missing")
            continue
        for metric in METRIC_UNITS:
            before_value = before["metrics"].get(metric, {}).get("value")
            after_value = after["metrics"].get(metric, {}).get("value")
            path = f"{key[0]}.{key[1]}.{metric}"
            if before_value is None or after_value is None:
                missing.append(f"{path}:null_measurement")
            elif metric != "tokens" and after_value > before_value * (1.0 + tolerance):
                regressions.append(path)
    return {
        "status": "blocked" if regressions or missing else "pass",
        "regressions": sorted(regressions),
        "missing_metrics": sorted(missing),
        "tolerance": tolerance,
    }


def run_benchmark(
    manifest: Mapping[str, Any], baseline: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    errors = validate_manifest(manifest)
    if errors:
        return {
            "schema": REPORT_SCHEMA,
            "version": VERSION,
            "status": "blocked",
            "manifest_errors": errors,
        }
    runs: list[dict[str, Any]] = []
    for agent in manifest["agents"]:
        for task in manifest["tasks"]:
            for warmup_number in range(manifest["warmups"]):
                runs.append(
                    run_one(
                        manifest, agent, task, run_number=warmup_number, warmup=True
                    )
                )
            for run_number in range(manifest["best_of_n"]):
                runs.append(
                    run_one(manifest, agent, task, run_number=run_number, warmup=False)
                )
    aggregates = aggregate_runs(manifest, runs)
    budget_gate = _budget_gate(manifest, aggregates)
    baseline_gate = (
        {"status": "unverified", "reason": "baseline_not_provided"}
        if baseline is None
        else compare_reports(baseline, {"aggregates": aggregates})
    )
    gate_status = "pass"
    if budget_gate["status"] != "pass" or baseline_gate["status"] != "pass":
        gate_status = "blocked" if baseline is not None else "unverified"
    return {
        "schema": REPORT_SCHEMA,
        "version": VERSION,
        "benchmark_id": manifest["benchmark_id"],
        "status": gate_status,
        "execution": {
            "mode": "runtime_supervised",
            "network_policy": manifest.get(
                "network_policy", "configured_by_agent_command"
            ),
            "local_llm": "paused",
            "runtime_command_sha256": _digest_command(manifest["runtime"]["command"]),
        },
        "runner": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "tokenizer": {
            "label": manifest["tokenizer"]["label"],
            "source": "task_complete event",
        },
        "best_of_n": manifest["best_of_n"],
        "warmups": manifest["warmups"],
        "runs": runs,
        "aggregates": aggregates,
        "gate": {"budgets": budget_gate, "baseline": baseline_gate},
        "limitations": [
            "No metric is inferred from missing events; null values retain their reasons.",
            "This report does not claim cross-agent capability or savings unless all four agents emit measured receipts.",
            "Local-model execution remains paused; token values require the configured tokenizer label.",
        ],
    }


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--jsonl-out", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = _read_json(args.manifest)
        errors = validate_manifest(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.validate_only:
        result = {
            "schema": MANIFEST_SCHEMA,
            "version": VERSION,
            "valid": not errors,
            "errors": errors,
        }
        if args.output:
            _write_json(args.output, result)
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not errors else 1
    baseline = None
    if args.baseline:
        try:
            baseline = _read_json(args.baseline)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    report = run_benchmark(manifest, baseline)
    if args.output:
        _write_json(args.output, report)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    if args.jsonl_out:
        args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)
        args.jsonl_out.write_text(
            "".join(
                json.dumps(run, sort_keys=True) + "\n" for run in report.get("runs", [])
            ),
            encoding="utf-8",
        )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
