"""Deterministic, offline harness for the Native benchmark fixture corpus.

The harness deliberately stays independent of the agent runtime.  The stub
provider exercises the same fixture, token, route, and report boundaries that
Native gates consume, while making zero network calls.  Wall-clock latency is
measured for the local work and is therefore reported as a measurement of the
runner, not as a claim about remote-provider latency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import tracemalloc
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.bench-fixture/v1"
REPORT_SCHEMA = "simplicio.bench-report/v1"
RECEIPT_SCHEMA = "simplicio.bench-receipt/v1"
GATE_SCHEMA = "simplicio.bench-gate/v1"
DEFAULT_FIXTURES = Path(__file__).with_name("fixtures") / "manifest.json"
DEFAULT_TOKEN_THRESHOLD_PCT = 5.0
# Local wall-clock measurements have more runner noise than token counts;
# retain the repository perf-gate's 20% default while allowing CI to tighten
# it for a controlled runner with --latency-threshold-pct.
DEFAULT_LATENCY_THRESHOLD_PCT = 20.0
EVIDENCE_PREFIXES = ("MEASURED|", "UNVERIFIED|")
SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:sk|api|token|secret|password)[-_][A-Za-z0-9_-]{24,}\b", re.I),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?:[A-Za-z]:\\|/home/|/Users/|/root/)[^\s\"']+"),
)


def canonical_json(value: Any) -> str:
    """Serialize values in the stable form used for fixture hashes."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def case_digest(case: dict[str, Any]) -> str:
    """Return the content address for a case, excluding its ``id`` field."""

    body = {key: case[key] for key in ("category", "input", "expected")}
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def fixture_digest(path: Path) -> str:
    """Hash the exact versioned bytes consumed by a benchmark run."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_sensitive(value: Any) -> list[str]:
    """Return matching sensitive-data patterns in a JSON-compatible value."""

    text = canonical_json(value)
    return [pattern.pattern for pattern in SENSITIVE_PATTERNS if pattern.search(text)]


def _numeric(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _category_rows(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        row["id"]: row
        for row in report.get("categories", [])
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }


def _metric_value(row: Mapping[str, Any], metric: str) -> Any:
    if "." not in metric:
        return row.get(metric)
    value: Any = row
    for part in metric.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def validate_report(
    report: Mapping[str, Any], manifest: Mapping[str, Any] | None = None
) -> list[str]:
    """Return stable errors for a benchmark receipt/report envelope.

    Reports are intentionally aggregate receipts rather than raw timing logs:
    this keeps CI artifacts small while preserving the category-level token and
    latency contract needed by the comparator.
    """

    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append(f"schema must be {REPORT_SCHEMA}")
    if report.get("receipt_schema") != RECEIPT_SCHEMA:
        errors.append(f"receipt_schema must be {RECEIPT_SCHEMA}")
    for field in ("fixture_set", "fixture_sha256", "provider", "token_estimator"):
        if not isinstance(report.get(field), str) or not report[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if not re.fullmatch(r"[0-9a-f]{64}", str(report.get("fixture_sha256", ""))):
        errors.append("fixture_sha256 must be a sha256 digest")
    evidence = report.get("evidence")
    if not isinstance(evidence, str) or not evidence.startswith(EVIDENCE_PREFIXES):
        errors.append("evidence must start with MEASURED| or UNVERIFIED|")
    for field in ("repeats", "warmup", "sample_count"):
        if (
            not isinstance(report.get(field), int)
            or isinstance(report[field], bool)
            or report[field] < 0
        ):
            errors.append(f"{field} must be a non-negative integer")
    if report.get("repeats", 0) < 1:
        errors.append("repeats must be positive")

    categories = report.get("categories")
    if not isinstance(categories, list) or not categories:
        errors.append("categories must be a non-empty list")
        return sorted(set(errors))
    expected_categories = {
        category["id"]: category
        for category in (manifest or {}).get("categories", [])
        if isinstance(category, Mapping) and isinstance(category.get("id"), str)
    }
    ids: list[str] = []
    for index, row in enumerate(categories):
        prefix = f"categories[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        category_id = row.get("id")
        if not isinstance(category_id, str) or not category_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
            continue
        ids.append(category_id)
        if expected_categories and category_id not in expected_categories:
            errors.append(f"{prefix}.id is not in the fixture manifest")
        for field in (
            "weight_pct",
            "input_tokens",
            "output_tokens",
            "peak_memory_bytes",
        ):
            if not _numeric(row.get(field)) or row[field] < 0:
                errors.append(f"{prefix}.{field} must be a non-negative number")
        if expected_categories and row.get("weight_pct") != expected_categories[
            category_id
        ].get("weight"):
            errors.append(f"{prefix}.weight_pct must match the fixture manifest")
        if expected_categories and row.get("route") != expected_categories[
            category_id
        ].get("route"):
            errors.append(f"{prefix}.route must match the fixture manifest")
        latency = row.get("latency_us")
        if not isinstance(latency, Mapping):
            errors.append(f"{prefix}.latency_us must be an object")
        else:
            for percentile in ("p50", "p95"):
                if not _numeric(latency.get(percentile)) or latency[percentile] < 0:
                    errors.append(
                        f"{prefix}.latency_us.{percentile} must be a non-negative number"
                    )
            if (
                _numeric(latency.get("p50"))
                and _numeric(latency.get("p95"))
                and latency["p50"] > latency["p95"]
            ):
                errors.append(f"{prefix}.latency_us.p50 must not exceed p95")
        if not isinstance(row.get("sample_count"), int) or row["sample_count"] < 1:
            errors.append(f"{prefix}.sample_count must be a positive integer")
    if len(ids) != len(set(ids)):
        errors.append("report category ids must be unique")
    if expected_categories and set(ids) != set(expected_categories):
        errors.append("report categories must cover every fixture category")
    if _numeric(report.get("sample_count")) and report["sample_count"] != sum(
        row.get("sample_count", 0) for row in categories if isinstance(row, Mapping)
    ):
        errors.append("sample_count must equal the sum of category sample_count values")
    if manifest is not None and report.get("fixture_set") != manifest.get(
        "fixture_set"
    ):
        errors.append("fixture_set must match the fixture manifest")
    return sorted(set(errors))


def _percent_change(before: float, after: float) -> float | None:
    return None if before == 0 else (after - before) / abs(before) * 100.0


def compare_reports(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    token_threshold_pct: float = DEFAULT_TOKEN_THRESHOLD_PCT,
    latency_threshold_pct: float = DEFAULT_LATENCY_THRESHOLD_PCT,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare two local receipts and fail closed on invalid or missing data."""

    errors = validate_report(before, manifest) + validate_report(after, manifest)
    if before.get("fixture_sha256") != after.get("fixture_sha256"):
        errors.append("before and after fixture_sha256 values must match")
    if before.get("fixture_set") != after.get("fixture_set"):
        errors.append("before and after fixture_set values must match")
    if not _numeric(token_threshold_pct) or token_threshold_pct < 0:
        errors.append("token_threshold_pct must be a non-negative number")
    if not _numeric(latency_threshold_pct) or latency_threshold_pct < 0:
        errors.append("latency_threshold_pct must be a non-negative number")

    metrics = (
        (
            "input_tokens",
            "tokens",
            float(token_threshold_pct) if _numeric(token_threshold_pct) else 0.0,
        ),
        (
            "output_tokens",
            "tokens",
            float(token_threshold_pct) if _numeric(token_threshold_pct) else 0.0,
        ),
        (
            "latency_us.p50",
            "latency",
            float(latency_threshold_pct) if _numeric(latency_threshold_pct) else 0.0,
        ),
        (
            "latency_us.p95",
            "latency",
            float(latency_threshold_pct) if _numeric(latency_threshold_pct) else 0.0,
        ),
    )
    comparisons: list[dict[str, Any]] = []
    regressions: list[str] = []
    before_rows = _category_rows(before)
    after_rows = _category_rows(after)
    for category_id in sorted(set(before_rows) | set(after_rows)):
        before_row = before_rows.get(category_id)
        after_row = after_rows.get(category_id)
        if before_row is None or after_row is None:
            errors.append(f"category {category_id} must be present in both receipts")
            continue
        for metric, family, threshold in metrics:
            before_value = _metric_value(before_row, metric)
            after_value = _metric_value(after_row, metric)
            path = f"{category_id}.{metric}"
            if not _numeric(before_value) or not _numeric(after_value):
                errors.append(f"{path} must be numeric in both receipts")
                continue
            delta = float(after_value) - float(before_value)
            change = _percent_change(float(before_value), float(after_value))
            regression = (
                after_value > before_value
                if before_value == 0
                else change is not None and change > threshold
            ) and after_value > before_value
            if regression:
                regressions.append(path)
            comparisons.append({
                "category": category_id,
                "metric": metric,
                "family": family,
                "before": before_value,
                "after": after_value,
                "delta": delta,
                "percent_change": change,
                "threshold_pct": threshold,
                "regression": regression,
            })
    errors = sorted(set(errors))
    blocked = bool(errors or regressions)
    evidence = "MEASURED|before/after local benchmark receipts compared"
    if before.get("evidence", "").startswith("UNVERIFIED|") or after.get(
        "evidence", ""
    ).startswith("UNVERIFIED|"):
        evidence = (
            "UNVERIFIED|comparison includes receipt(s) without measured provenance"
        )
    return {
        "schema": GATE_SCHEMA,
        "receipt_schema": RECEIPT_SCHEMA,
        "fixture_set": before.get("fixture_set"),
        "before_fixture_sha256": before.get("fixture_sha256"),
        "after_fixture_sha256": after.get("fixture_sha256"),
        "status": "blocked" if blocked else "pass",
        "evidence": evidence,
        "errors": errors,
        "regressions": sorted(regressions),
        "comparisons": comparisons,
        "summary": {
            "metric_count": len(comparisons),
            "regression_count": len(regressions),
            "error_count": len(errors),
        },
        "limitations": [
            "The stub provider measures only local harness work; it is not remote-provider latency.",
            "Fixture weights are provisional until scrubbed receipt mining is available.",
        ],
    }


def load_manifest(path: str | Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    """Load and validate a fixture manifest before any benchmark work."""

    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"unsupported fixture schema: {manifest.get('schema')!r}")

    categories = manifest.get("categories")
    cases = manifest.get("cases")
    if not isinstance(categories, list) or not isinstance(cases, list):
        raise ValueError("fixture manifest requires categories and cases arrays")
    category_map = {entry.get("id"): entry for entry in categories}
    if len(category_map) != len(categories) or len(category_map) < 8:
        raise ValueError("fixture manifest requires at least eight unique categories")
    if sum(entry.get("weight", 0) for entry in categories) != 100:
        raise ValueError("category weights must sum to 100")

    ids: set[str] = set()
    counts: Counter[str] = Counter()
    for case in cases:
        if not {"id", "category", "input", "expected"}.issubset(case):
            raise ValueError("every case requires id, category, input, and expected")
        if case["category"] not in category_map:
            raise ValueError(f"unknown case category: {case['category']!r}")
        if case["id"] in ids or case["id"] != case_digest(case):
            raise ValueError(f"invalid or duplicate content address: {case['id']!r}")
        if case["expected"].get("route") != category_map[case["category"]].get("route"):
            raise ValueError(f"route mismatch in case {case['id']}")
        if scan_sensitive(case):
            raise ValueError(f"sensitive data detected in case {case['id']}")
        ids.add(case["id"])
        counts[case["category"]] += 1
    if any(counts[entry["id"]] < 5 for entry in categories):
        raise ValueError("every category requires at least five cases")
    if scan_sensitive({
        key: value for key, value in manifest.items() if key != "sampling"
    }):
        raise ValueError("sensitive data detected in fixture manifest")
    return manifest


def _percentile(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile, stable for small repeated samples."""

    if not values:
        raise ValueError("cannot calculate a percentile without samples")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _tokens(value: Any) -> int:
    """Portable token proxy used by the stub (UTF-8 characters / four)."""

    return (len(canonical_json(value).encode("utf-8")) + 3) // 4


def _stub_run(case: dict[str, Any]) -> dict[str, Any]:
    """Execute one case without I/O, network, or runtime imports."""

    input_started = time.perf_counter_ns()
    input_tokens = _tokens(case["input"])
    output_tokens = _tokens(case["expected"]["output"])
    token_us = (time.perf_counter_ns() - input_started) / 1000

    route_started = time.perf_counter_ns()
    route = case["expected"]["route"]
    route_us = (time.perf_counter_ns() - route_started) / 1000

    execute_started = time.perf_counter_ns()
    output = case["expected"]["output"]
    hashlib.sha256(
        canonical_json({"route": route, "output": output}).encode("utf-8")
    ).hexdigest()
    execute_us = (time.perf_counter_ns() - execute_started) / 1000
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "route": route,
        "token_us": token_us,
        "route_us": route_us,
        "execute_us": execute_us,
        "output": output,
    }


def run_benchmark(
    fixture_path: str | Path = DEFAULT_FIXTURES,
    *,
    provider: str = "stub",
    repeats: int = 100,
    warmup: int = 5,
) -> dict[str, Any]:
    """Run the fixture corpus and return a stable v1 report envelope."""

    if provider != "stub":
        raise ValueError(
            "bounded harness supports only --provider stub; no network provider is implemented"
        )
    if repeats < 1 or warmup < 0:
        raise ValueError("repeats must be positive and warmup cannot be negative")
    path = Path(fixture_path)
    manifest = load_manifest(path)
    samples: dict[str, list[dict[str, Any]]] = {
        entry["id"]: [] for entry in manifest["categories"]
    }

    # Keep tracemalloc out of the latency loop: its tracing hooks materially
    # inflate and destabilize sub-millisecond measurements. Memory is sampled
    # in a separate pass and remains in the report as its own metric.
    for case in manifest["cases"]:
        for _ in range(warmup):
            _stub_run(case)
        for _ in range(repeats):
            started = time.perf_counter_ns()
            result = _stub_run(case)
            result["latency_us"] = (time.perf_counter_ns() - started) / 1000
            samples[case["category"]].append(result)

    memory_by_category: dict[str, int] = {
        entry["id"]: 0 for entry in manifest["categories"]
    }
    tracemalloc.start()
    try:
        for case in manifest["cases"]:
            _stub_run(case)
            memory_by_category[case["category"]] = max(
                memory_by_category[case["category"]], tracemalloc.get_traced_memory()[1]
            )
    finally:
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    categories = []
    for category in manifest["categories"]:
        rows = samples[category["id"]]
        categories.append({
            "id": category["id"],
            "weight_pct": category["weight"],
            "route": category["route"],
            "sample_count": len(rows),
            "input_tokens": sum(row["input_tokens"] for row in rows) / len(rows),
            "output_tokens": sum(row["output_tokens"] for row in rows) / len(rows),
            "latency_us": {
                "p50": _percentile([row["latency_us"] for row in rows], 0.50),
                "p95": _percentile([row["latency_us"] for row in rows], 0.95),
            },
            "stages_us": {
                "token": _percentile([row["token_us"] for row in rows], 0.50),
                "route": _percentile([row["route_us"] for row in rows], 0.50),
                "execute": _percentile([row["execute_us"] for row in rows], 0.50),
            },
            "peak_memory_bytes": max(memory_by_category[category["id"]], peak_memory),
        })
    return {
        "schema": REPORT_SCHEMA,
        "receipt_schema": RECEIPT_SCHEMA,
        "fixture_set": manifest["fixture_set"],
        "fixture_sha256": fixture_digest(path),
        "provider": provider,
        "token_estimator": "utf8_bytes_div4_ceil",
        "repeats": repeats,
        "warmup": warmup,
        "sample_count": sum(len(rows) for rows in samples.values()),
        "categories": categories,
        "evidence": "MEASURED|stub execution, token counts, local stage latency, and tracemalloc peak",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run the offline stub benchmark")
    run_parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    run_parser.add_argument("--provider", choices=("stub",), default="stub")
    run_parser.add_argument("--repeats", type=int, default=100)
    run_parser.add_argument("--warmup", type=int, default=5)
    run_parser.add_argument("--json", type=Path, help="write the report to a file")
    compare_parser = subparsers.add_parser(
        "compare", help="compare before/after local receipts and enforce thresholds"
    )
    compare_parser.add_argument(
        "--before", "--baseline", dest="before", type=Path, required=True
    )
    compare_parser.add_argument(
        "--after", "--candidate", dest="after", type=Path, required=True
    )
    compare_parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    compare_parser.add_argument(
        "--token-threshold-pct", type=float, default=DEFAULT_TOKEN_THRESHOLD_PCT
    )
    compare_parser.add_argument(
        "--latency-threshold-pct", type=float, default=DEFAULT_LATENCY_THRESHOLD_PCT
    )
    compare_parser.add_argument(
        "--json", type=Path, help="write the gate receipt to a file"
    )
    args = parser.parse_args(argv)
    if args.command == "run":
        report = run_benchmark(
            args.fixtures,
            provider=args.provider,
            repeats=args.repeats,
            warmup=args.warmup,
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0

    try:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        manifest = load_manifest(args.fixtures)
        if not isinstance(before, Mapping) or not isinstance(after, Mapping):
            raise ValueError("before and after receipts must be JSON objects")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    gate = compare_reports(
        before,
        after,
        manifest=manifest,
        token_threshold_pct=args.token_threshold_pct,
        latency_threshold_pct=args.latency_threshold_pct,
    )
    rendered = json.dumps(gate, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
