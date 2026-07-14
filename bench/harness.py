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
import time
import tracemalloc
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.bench-fixture/v1"
REPORT_SCHEMA = "simplicio.bench-report/v1"
DEFAULT_FIXTURES = Path(__file__).with_name("fixtures") / "manifest.json"
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
    args = parser.parse_args(argv)
    report = run_benchmark(
        args.fixtures, provider=args.provider, repeats=args.repeats, warmup=args.warmup
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
