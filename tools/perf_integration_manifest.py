#!/usr/bin/env python3
"""Generate and validate the deterministic performance integration manifest.

The manifest is deliberately a description of evidence, rather than a test
that stops at the first failed check.  Every stage is classified independently
so a CI report still explains all of the ways an optimisation is integrated.
The output contains no timestamps, host paths, import versions, or other
machine-specific values and is therefore suitable for committing as a
fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from pathlib import PureWindowsPath
from typing import Any, Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "simplicio.perf-integration-manifest/v1"
VERSION = 1
STAGES = (
    "PRESENT",
    "SAME_SOURCE",
    "BUILT",
    "INSTALLED",
    "IMPORTABLE",
    "CALLED",
    "E2E_PROVEN",
    "DEFAULT_ON",
    "BENCHMARKED",
    "REGRESSION_GATED",
)
PASSING_STATUSES = frozenset(("pass", "not_applicable"))
VALID_STATUSES = frozenset(("pass", "fail", "not_applicable", "unknown"))
REQUIRED_AXIS_NAMES = (
    "fast-json",
    "uvloop",
    "rust-fast-path",
    "streaming",
    "async-dag-thread-pool",
    "tool-batch-timeout",
    "rate-limit-dedup",
    "http-pool",
    "warm-daemon",
    "prompt-transport-registry",
    "prompt-cache",
    "compression-toon",
    "kernel-binding",
    "installation-profiles",
    "hermes-turbo-pipeline",
)
RUNTIME_UNVERIFIED_REASON = (
    "UNVERIFIED| runtime obrigatório ausente; nenhum Qwen/Ollama/llama.cpp/"
    "MiniCPM/LLM local disponível"
)


def _is_canonical_source_path(value: Any) -> bool:
    """Return whether ``value`` is a repository-relative POSIX path."""

    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and not PureWindowsPath(value).drive
        and value == path.as_posix()
        and "." not in path.parts
        and ".." not in path.parts
    )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


@dataclass(frozen=True)
class StageResult:
    """One stage outcome; stages are never implicitly skipped by another."""

    status: str
    reason: str = ""
    evidence: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in PASSING_STATUSES

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.status, "ok": self.ok}
        if self.reason:
            result["reason"] = self.reason
        if self.evidence:
            result["evidence"] = list(self.evidence)
        return result


@dataclass
class AxisResult:
    name: str
    description: str
    owner: str
    platforms: tuple[str, ...]
    related_issues: tuple[str, ...]
    source_commit: dict[str, Any]
    source: tuple[str, ...]
    call_sites: tuple[dict[str, str], ...]
    config: tuple[dict[str, str], ...]
    fallback: dict[str, Any]
    benchmark: dict[str, Any]
    stages: dict[str, StageResult] = field(default_factory=dict)

    def mark(
        self,
        stage: str,
        ok: bool | None = None,
        *,
        status: str | None = None,
        reason: str = "",
        evidence: tuple[str, ...] = (),
    ) -> None:
        if status is None:
            if ok is None:
                status = "unknown"
            else:
                status = "pass" if ok else "fail"
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid stage status: {status}")
        self.stages[stage] = StageResult(status, reason, evidence)

    @property
    def ok(self) -> bool:
        return all(
            self.stages.get(stage, StageResult("unknown")).ok for stage in STAGES
        )

    def as_dict(self, repo_root: Path) -> dict[str, Any]:
        source_sha256 = {
            _relative(path, repo_root): _sha256(repo_root / path)
            for path in sorted(self.source)
        }
        stage_results = {
            stage: self.stages.get(stage, StageResult("unknown")).as_dict()
            for stage in STAGES
        }
        # ``stages`` retains the compact boolean view used by the original
        # checker.  ``stage_results`` and ``stage_status`` are the v1 API.
        return {
            "name": self.name,
            "description": self.description,
            "owner": self.owner,
            "platforms": list(self.platforms),
            "related_issues": list(self.related_issues),
            "source_commit": dict(self.source_commit),
            "ok": self.ok,
            "stages": {stage: result["ok"] for stage, result in stage_results.items()},
            "stage_status": {
                stage: result["status"] for stage, result in stage_results.items()
            },
            "stage_results": stage_results,
            "source": list(sorted(self.source)),
            "source_sha256": source_sha256,
            "call_sites": [dict(item) for item in self.call_sites],
            "config": [dict(item) for item in self.config],
            "fallback": self.fallback,
            "benchmark": dict(self.benchmark),
        }


@dataclass(frozen=True)
class AxisSpec:
    name: str
    description: str
    owner: str
    platforms: tuple[str, ...]
    related_issues: tuple[str, ...]
    source_commit: dict[str, Any]
    source: tuple[str, ...]
    call_sites: tuple[dict[str, str], ...]
    config: tuple[dict[str, str], ...]
    fallback: dict[str, Any]
    check: Callable[[AxisResult, Path], None]


def _relative(path: str | Path, repo_root: Path) -> str:
    """Return a stable POSIX path, never an absolute host path."""

    value = Path(path)
    try:
        value = value.relative_to(repo_root)
    except ValueError:
        pass
    return value.as_posix()


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _text(repo_root: Path, path: str) -> str:
    try:
        return (repo_root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _contains(repo_root: Path, path: str, needle: str) -> bool:
    return needle in _text(repo_root, path)


def _importable(module_name: str, repo_root: Path) -> bool:
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(repo_root))
        importlib.invalidate_caches()
        importlib.import_module(module_name)
        return True
    except Exception:
        return False
    finally:
        sys.path[:] = old_path


def _module_attr(module_name: str, attr: str, repo_root: Path) -> bool:
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(repo_root))
        module = importlib.import_module(module_name)
        return hasattr(module, attr)
    except Exception:
        return False
    finally:
        sys.path[:] = old_path


def _exercise_fast_json(repo_root: Path) -> tuple[bool, str]:
    """Exercise the selected fast backend without measuring performance.

    The integration manifest must prove that the fast-json optimization is
    actually wired into the public serializer path, not only that optional
    packages happen to be importable.  Backend markers keep this receipt
    deterministic and avoid making a performance claim from a smoke test.
    """

    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(repo_root))
        importlib.invalidate_caches()
        module = importlib.import_module("agent.serde.fast_json")
        payload = {"kind": "perf-receipt", "items": [1, 2, 3]}
        backend: str
        if module.has_orjson():
            backend = "orjson"
            encoder = module.orjson.dumps
            decoder = module.orjson.loads
        elif module.has_msgspec():
            backend = "msgspec"
            encoder = module.msgspec.json.encode
            decoder = module.msgspec.json.decode
        else:
            return False, "no fast backend available"

        called = {"encode": False, "decode": False}

        def mark_encode(value: Any) -> Any:
            called["encode"] = True
            return encoder(value)

        def mark_decode(value: Any) -> Any:
            called["decode"] = True
            return decoder(value)

        if backend == "orjson":
            module.orjson.dumps = mark_encode
            module.orjson.loads = mark_decode
        else:
            module.msgspec.json.encode = mark_encode
            module.msgspec.json.decode = mark_decode
        try:
            encoded = module.dumps(payload)
            decoded = module.loads(encoded)
        finally:
            if backend == "orjson":
                module.orjson.dumps = encoder
                module.orjson.loads = decoder
            else:
                module.msgspec.json.encode = encoder
                module.msgspec.json.decode = decoder

        ok = (
            called["encode"]
            and called["decode"]
            and isinstance(encoded, bytes)
            and decoded == payload
        )
        return (
            ok,
            f"backend={backend}; encode=called; decode=called; round_trip={'pass' if ok else 'fail'}",
        )
    except Exception as exc:  # pragma: no cover - defensive receipt path
        return False, f"exercise failed: {type(exc).__name__}"
    finally:
        sys.path[:] = old_path


def _spec_result(spec: AxisSpec) -> AxisResult:
    return AxisResult(
        name=spec.name,
        description=spec.description,
        owner=spec.owner,
        platforms=spec.platforms,
        related_issues=spec.related_issues,
        source_commit=dict(spec.source_commit),
        source=spec.source,
        call_sites=spec.call_sites,
        config=spec.config,
        fallback=dict(spec.fallback),
        benchmark={
            "kind": "E2E",
            "baseline": None,
            "candidate": None,
            "p50": None,
            "p95": None,
            "gain": None,
            "cpu": None,
            "rss": None,
            "tokens": None,
            "cost": None,
            "status": "UNVERIFIED",
            "reason": RUNTIME_UNVERIFIED_REASON,
        },
    )


def _module_from_source(path: str) -> str | None:
    if not path.endswith(".py") or path.startswith("rust_ext/"):
        return None
    return path[:-3].replace("/", ".")


def _check_static_axis(result: AxisResult, repo_root: Path) -> None:
    """Collect static receipts without promoting them to runtime evidence."""

    present = all((repo_root / path).is_file() for path in result.source)
    result.mark("PRESENT", present, evidence=result.source if present else ())
    result.mark(
        "SAME_SOURCE",
        status="unknown",
        reason="UNVERIFIED| Hermes Turbo checkout/commit was not supplied",
    )
    result.mark(
        "BUILT",
        status="unknown",
        reason="UNVERIFIED| no clean build receipt was supplied",
    )
    importable_modules = [
        module
        for module in (_module_from_source(path) for path in result.source)
        if module
    ]
    # Avoid importing the checkout here: optional dependency availability would
    # make the committed receipt vary by host. Clean installed-artifact import
    # belongs to INSTALLED/E2E_PROVEN and remains independently unverified.
    importable = present and bool(importable_modules)
    result.mark(
        "INSTALLED",
        status="unknown",
        reason="UNVERIFIED| checkout import is not an installed-artifact receipt",
    )
    result.mark(
        "IMPORTABLE",
        importable,
        reason=(
            "source import path present; dependency import not runtime-proven"
            if importable
            else "no Python source import path present"
        ),
        evidence=tuple(importable_modules),
    )
    called = all(
        (repo_root / call["path"]).is_file()
        and _contains(repo_root, call["path"], call["symbol"])
        for call in result.call_sites
    )
    result.mark(
        "CALLED",
        called,
        reason=("static call-site markers found" if called else "static call-site marker missing"),
        evidence=tuple(f"{c['path']}:{c['symbol']}" for c in result.call_sites),
    )
    result.mark(
        "E2E_PROVEN",
        status="unknown",
        reason=RUNTIME_UNVERIFIED_REASON,
    )
    config_present = all(
        (repo_root / item["path"]).is_file()
        and _contains(repo_root, item["path"], item["key"])
        for item in result.config
    )
    result.mark(
        "DEFAULT_ON",
        config_present,
        reason=("config/default marker present" if config_present else "config/default marker missing"),
        evidence=tuple(f"{c['path']}:{c['key']}" for c in result.config),
    )
    result.mark(
        "BENCHMARKED",
        status="unknown",
        reason=RUNTIME_UNVERIFIED_REASON,
    )
    result.mark(
        "REGRESSION_GATED",
        status="unknown",
        reason="UNVERIFIED| no approved baseline and regression receipt supplied",
    )


_SOURCE_COMMIT_UNVERIFIED = {
    "value": None,
    "status": "UNVERIFIED",
    "reason": "Hermes Turbo repository/commit was not supplied to this local audit",
}


def _axis(
    name: str,
    description: str,
    source: tuple[str, ...],
    call_sites: tuple[dict[str, str], ...],
    config: tuple[dict[str, str], ...],
    related_issues: tuple[str, ...],
    fallback_paths: tuple[str, ...],
) -> AxisSpec:
    return AxisSpec(
        name=name,
        description=description,
        owner="perf-audit",
        platforms=("linux", "macos", "windows", "termux"),
        related_issues=related_issues,
        source_commit=dict(_SOURCE_COMMIT_UNVERIFIED),
        source=source,
        call_sites=call_sites,
        config=config,
        fallback={
            "available": True,
            "paths": list(fallback_paths),
            "description": "documented fallback path; activation requires runtime receipt",
        },
        check=_check_static_axis,
    )


AXIS_SPECS: tuple[AxisSpec, ...] = (
    _axis(
        "fast-json", "orjson/msgspec serializer with stdlib fallback.",
        ("agent/serde/fast_json.py", "agent/serde/__init__.py", "agent/_fastjson.py"),
        ({"path": "run_agent.py", "symbol": "from agent._fastjson"}, {"path": "agent/telemetry/receipts.py", "symbol": "from agent.serde"}),
        ({"path": "pyproject.toml", "key": "orjson>="}, {"path": "pyproject.toml", "key": "msgspec>="}),
        ("#220", "#70"), ("agent/_fastjson.py",),
    ),
    _axis(
        "uvloop", "Optional libuv event-loop policy for async entrypoints.",
        ("agent/uvloop_utils.py", "agent/async_dag/uvloop_runner.py"),
        ({"path": "hermes_cli/main.py", "symbol": "install_uvloop_policy"}, {"path": "hermes_cli/gateway.py", "symbol": "install_uvloop_policy"}),
        ({"path": "pyproject.toml", "key": "uvloop>="},),
        ("#220", "#70"), ("agent/uvloop_utils.py",),
    ),
    _axis(
        "rust-fast-path", "rust_ext and agent/_hermes_fast native hot path.",
        ("rust_ext/src/lib.rs", "rust_ext/pyproject.toml", "agent/_hermes_fast.py"),
        ({"path": "agent/_hermes_fast.py", "symbol": "rust_ext"}, {"path": "scripts/importer/import.sh", "symbol": "agent/_hermes_fast.py"}),
        ({"path": "rust_ext/pyproject.toml", "key": "maturin"}, {"path": "pyproject.toml", "key": "maturin"}),
        ("#220", "#113"), ("agent/_hermes_fast.py",),
    ),
    _axis(
        "streaming", "Incremental/streaming parsing and stream diagnostics.",
        ("agent/stream_diag.py", "run_agent.py"),
        ({"path": "run_agent.py", "symbol": "stream"}, {"path": "agent/stream_diag.py", "symbol": "stream"}),
        ({"path": "pyproject.toml", "key": "stream"},),
        ("#220", "#18"), ("agent/stream_diag.py",),
    ),
    _axis(
        "async-dag-thread-pool", "Async DAG executor and current thread-pool path.",
        ("agent/async_dag/executor.py", "agent/async_dag/__init__.py"),
        ({"path": "agent/async_dag/executor.py", "symbol": "ThreadPoolExecutor"}, {"path": "run_agent.py", "symbol": "async_dag"}),
        ({"path": "pyproject.toml", "key": "async_dag"},),
        ("#220", "#22"), ("agent/async_dag/executor.py",),
    ),
    _axis(
        "tool-batch-timeout", "Timeout boundary for batched tool execution.",
        ("hermes_cli/timeouts.py", "run_agent.py"),
        ({"path": "run_agent.py", "symbol": "get_provider_request_timeout"}, {"path": "hermes_cli/timeouts.py", "symbol": "timeout"}),
        ({"path": "hermes_cli/config.py", "key": "timeout"},),
        ("#220", "#70"), ("hermes_cli/timeouts.py",),
    ),
    _axis(
        "rate-limit-dedup", "Rate limiter, rate tracking, and in-flight deduplication.",
        ("agent/tier_rate_limiter.py", "agent/rate_limit_tracker.py", "hermes_cli/skills_hub.py"),
        ({"path": "run_agent.py", "symbol": "rate_limit"}, {"path": "hermes_cli/skills_hub.py", "symbol": "deduped"}),
        ({"path": "pyproject.toml", "key": "rate"},),
        ("#220", "#70"), ("agent/rate_limit_tracker.py",),
    ),
    _axis(
        "http-pool", "Reusable HTTP connection pool path.",
        ("agent/net/http_pool.py", "agent/net/__init__.py"),
        ({"path": "run_agent.py", "symbol": "http_client"}, {"path": "agent/net/http_pool.py", "symbol": "Pool"}),
        ({"path": "pyproject.toml", "key": "http"},),
        ("#220", "#110"), ("urllib",),
    ),
    _axis(
        "warm-daemon", "Warm daemon/prewarm process path.",
        ("hermes_cli/daemon.py", "fixtures/native/daemon_hot_path_contract.json"),
        ({"path": "hermes_cli/daemon.py", "symbol": "daemon"}, {"path": "hermes_cli/main.py", "symbol": "daemon"}),
        ({"path": "hermes_cli/config.py", "key": "daemon"},),
        ("#220", "#110"), ("hermes_cli/daemon.py",),
    ),
    _axis(
        "prompt-transport-registry", "simplicio_prompt and transport registry wiring.",
        ("agent/simplicio_prompt.py", "agent/prompt_builder.py"),
        ({"path": "run_agent.py", "symbol": "simplicio_prompt"}, {"path": "agent/prompt_builder.py", "symbol": "transport"}),
        ({"path": "pyproject.toml", "key": "prompt"},),
        ("#220", "#18"), ("agent/prompt_builder.py",),
    ),
    _axis(
        "prompt-cache", "Prompt cache reuse and provider cache policy.",
        ("agent/prompt_caching.py", "run_agent.py"),
        ({"path": "run_agent.py", "symbol": "_anthropic_prompt_cache_policy"}, {"path": "agent/prompt_caching.py", "symbol": "cache"}),
        ({"path": "hermes_cli/config.py", "key": "prompt_cache"},),
        ("#220", "#22"), ("agent/prompt_caching.py",),
    ),
    _axis(
        "compression-toon", "Prompt compression, compression receipt, and TOON encoding.",
        ("agent/conversation_compression.py", "agent/toon_codec.py", "agent/toon_boundary.py"),
        ({"path": "run_agent.py", "symbol": "conversation_compression"}, {"path": "agent/toon_boundary.py", "symbol": "toon"}),
        ({"path": "pyproject.toml", "key": "toon"},),
        ("#220", "#112"), ("agent/conversation_compression.py",),
    ),
    _axis(
        "kernel-binding", "Gate, checkpoint, edit, orient, memory, and ledger bindings.",
        ("agent/golden_path.py", "agent/reversible_path.py", "agent/verification_evidence.py"),
        ({"path": "agent/golden_path.py", "symbol": "checkpoint"}, {"path": "agent/golden_path.py", "symbol": "ledger"}),
        ({"path": "runtime.lock", "key": "runtime"},),
        ("#220", "#116"), ("agent/reversible_path.py",),
    ),
    _axis(
        "installation-profiles", "Official installer, wheels, Docker, Windows, and lean/Termux profiles.",
        ("pyproject.toml", "scripts/install.sh", "scripts/install.ps1", "docker/entrypoint.sh"),
        ({"path": "scripts/install.sh", "symbol": "SIMPLICIO_AGENT_LEAN"}, {"path": "scripts/install.ps1", "symbol": "Install"}),
        ({"path": "pyproject.toml", "key": "optional-dependencies"}, {"path": "pyproject.toml", "key": "Termux"}),
        ("#220", "#187"), ("agent/_fastjson.py",),
    ),
    _axis(
        "hermes-turbo-pipeline", "Hermes → Hermes Turbo → Simplicio Agent provenance pipeline.",
        ("scripts/importer/import.sh", "scripts/sync/ecosystem-sync.sh", "docs/SYNC_PIPELINE.md"),
        ({"path": "scripts/importer/import.sh", "symbol": "Pipeline:"}, {"path": "docs/SYNC_PIPELINE.md", "symbol": "Hermes Turbo Agent"}),
        ({"path": "docs/SYNC_PIPELINE.md", "key": "hermes-turbo-agent"},),
        ("#220", "#18", "#158"), ("agent/",),
    ),
)


def run_all(repo_root: Path = REPO_ROOT) -> list[AxisResult]:
    """Evaluate every stage for every axis, even when earlier stages fail."""

    results: list[AxisResult] = []
    for spec in AXIS_SPECS:
        result = _spec_result(spec)
        try:
            spec.check(result, repo_root)
        except Exception as exc:  # pragma: no cover - defensive report path
            result.mark(
                "UNKNOWN", status="unknown", reason=f"unexpected checker error: {exc}"
            )
            for stage in STAGES:
                result.stages.setdefault(
                    stage, StageResult("unknown", "checker did not classify stage")
                )
        results.append(result)
    return results


def generate_manifest(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Generate a stable v1 JSON-compatible document for ``repo_root``."""

    axes = [result.as_dict(repo_root) for result in run_all(repo_root)]
    failed = sum(not axis["ok"] for axis in axes)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "generator": "tools/perf_integration_manifest.py",
        "repo": ".",
        "axes": axes,
        "summary": {"axis_count": len(axes), "failed": failed, "ok": failed == 0},
    }


def validate_manifest(
    document: Mapping[str, Any], repo_root: Path | None = None
) -> list[str]:
    """Return deterministic validation errors; an empty list means valid."""

    errors: list[str] = []
    if document.get("schema") != SCHEMA:
        errors.append("schema must be simplicio.perf-integration-manifest/v1")
    if document.get("version") != VERSION:
        errors.append("version must be 1")
    if document.get("generator") != "tools/perf_integration_manifest.py":
        errors.append("generator must be tools/perf_integration_manifest.py")
    if document.get("repo") != ".":
        errors.append("repo must be .")
    axes = document.get("axes")
    if not isinstance(axes, list) or not axes:
        errors.append("axes must be a non-empty list")
        return errors
    names: list[str] = []
    axis_ok: list[bool] = []
    for index, axis in enumerate(axes):
        prefix = f"axes[{index}]"
        if not isinstance(axis, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        name = axis.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{prefix}.name must be a non-empty string")
        else:
            names.append(name)
        if not isinstance(axis.get("description"), str) or not axis["description"]:
            errors.append(f"{prefix}.description must be a non-empty string")
        if not isinstance(axis.get("ok"), bool):
            errors.append(f"{prefix}.ok must be a boolean")
        else:
            axis_ok.append(axis["ok"])
        source = axis.get("source")
        hashes = axis.get("source_sha256")
        if not isinstance(source, list) or not source:
            errors.append(f"{prefix}.source must be a non-empty list")
            source_values: list[Any] = []
        else:
            source_values = source
            source_paths_valid = all(
                _is_canonical_source_path(relative) for relative in source_values
            )
            for relative in source_values:
                if not _is_canonical_source_path(relative):
                    errors.append(f"{prefix}.source has non-canonical path: {relative}")
            if source_paths_valid and source_values != sorted(set(source_values)):
                errors.append(f"{prefix}.source must be sorted and unique")
        if not isinstance(hashes, Mapping):
            errors.append(f"{prefix}.source_sha256 must hash every source path")
        else:
            hash_keys = list(hashes)
            if source_values and (
                not all(
                    _is_canonical_source_path(relative) for relative in source_values
                )
                or not all(isinstance(key, str) for key in hash_keys)
                or set(hash_keys) != set(source_values)
            ):
                errors.append(f"{prefix}.source_sha256 must hash every source path")
            if not all(isinstance(key, str) for key in hash_keys):
                errors.append(f"{prefix}.source_sha256 keys must be strings")
            elif hash_keys != sorted(hash_keys):
                errors.append(f"{prefix}.source_sha256 keys must be sorted")
            for relative, expected in hashes.items():
                if not _is_canonical_source_path(relative):
                    errors.append(
                        f"{prefix}.source_sha256 has non-canonical path: {relative}"
                    )
                if not _is_sha256(expected):
                    errors.append(
                        f"{prefix}.source_sha256 must contain lowercase SHA-256: {relative}"
                    )
        results = axis.get("stage_results")
        if not isinstance(results, Mapping):
            errors.append(f"{prefix}.stage_results must be an object")
        else:
            missing = [stage for stage in STAGES if stage not in results]
            if missing:
                errors.append(f"{prefix}.stage_results missing: {','.join(missing)}")
            extra = sorted(set(results) - set(STAGES), key=str)
            if extra:
                errors.append(f"{prefix}.stage_results has unknown: {','.join(extra)}")
            for stage, value in results.items():
                if (
                    stage not in STAGES
                    or not isinstance(value, Mapping)
                    or value.get("status") not in VALID_STATUSES
                ):
                    errors.append(f"{prefix}.stage_results.{stage} has invalid status")
                    continue
                if value.get("ok") is not (value["status"] in PASSING_STATUSES):
                    errors.append(
                        f"{prefix}.stage_results.{stage}.ok disagrees with status"
                    )
                if "reason" in value and not isinstance(value["reason"], str):
                    errors.append(
                        f"{prefix}.stage_results.{stage}.reason must be a string"
                    )
                if "evidence" in value and (
                    not isinstance(value["evidence"], list)
                    or any(not isinstance(item, str) for item in value["evidence"])
                ):
                    errors.append(
                        f"{prefix}.stage_results.{stage}.evidence must be a string list"
                    )
        statuses = axis.get("stage_status")
        if not isinstance(statuses, Mapping):
            errors.append(f"{prefix}.stage_status must be an object")
        else:
            if set(statuses) != set(STAGES):
                errors.append(f"{prefix}.stage_status must contain exactly all stages")
        compact = axis.get("stages")
        if not isinstance(compact, Mapping):
            errors.append(f"{prefix}.stages must be an object")
        elif set(compact) != set(STAGES) or any(
            not isinstance(compact.get(stage), bool) for stage in STAGES
        ):
            errors.append(f"{prefix}.stages must contain boolean values for all stages")
        if (
            isinstance(results, Mapping)
            and isinstance(statuses, Mapping)
            and isinstance(compact, Mapping)
        ):
            for stage in STAGES:
                result = results.get(stage)
                status = statuses.get(stage)
                if not isinstance(result, Mapping) or status not in VALID_STATUSES:
                    continue
                expected_ok = status in PASSING_STATUSES
                if status != result.get("status"):
                    errors.append(f"{prefix}.{stage} status receipt disagrees")
                if compact.get(stage) is not expected_ok:
                    errors.append(f"{prefix}.{stage} boolean receipt disagrees")
        if isinstance(axis.get("ok"), bool) and isinstance(results, Mapping):
            complete = all(
                isinstance(results.get(stage), Mapping)
                and results[stage].get("status") in PASSING_STATUSES
                for stage in STAGES
            )
            if axis["ok"] is not complete:
                errors.append(f"{prefix}.ok disagrees with stage results")
        for key in ("call_sites", "config", "fallback"):
            if key not in axis:
                errors.append(f"{prefix}.{key} is required")
        for key in ("owner", "platforms", "related_issues", "source_commit", "benchmark"):
            if key not in axis:
                errors.append(f"{prefix}.{key} is required")
        benchmark = axis.get("benchmark")
        if not isinstance(benchmark, Mapping):
            errors.append(f"{prefix}.benchmark must be an object")
        else:
            required_benchmark = {
                "kind", "baseline", "candidate", "p50", "p95", "gain",
                "cpu", "rss", "tokens", "cost", "status", "reason",
            }
            if not required_benchmark.issubset(benchmark):
                errors.append(f"{prefix}.benchmark is incomplete")
            if benchmark.get("status") == "UNVERIFIED" and not benchmark.get("reason"):
                errors.append(f"{prefix}.benchmark UNVERIFIED requires a reason")
    if len(names) != len(set(names)):
        errors.append("axis names must be unique")
    summary = document.get("summary")
    if not isinstance(summary, Mapping):
        errors.append("summary must be an object")
    else:
        if summary.get("axis_count") != len(axes):
            errors.append("summary.axis_count disagrees with axes")
        failed = sum(not value for value in axis_ok)
        if summary.get("failed") != failed:
            errors.append("summary.failed disagrees with axis results")
        if summary.get("ok") is not (failed == 0 and len(axis_ok) == len(axes)):
            errors.append("summary.ok disagrees with axis results")
    if repo_root is not None:
        for index, axis in enumerate(axes):
            if not isinstance(axis, Mapping) or not isinstance(
                axis.get("source_sha256"), Mapping
            ):
                continue
            for relative, expected in axis["source_sha256"].items():
                if not _is_canonical_source_path(relative) or not _is_sha256(expected):
                    continue
                actual = _sha256(repo_root / relative)
                if actual != expected:
                    errors.append(f"axes[{index}].source_sha256 mismatch: {relative}")
    return sorted(set(errors))


def _write_json(document: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=str(REPO_ROOT), help="repository root to inspect"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the generated manifest to stdout"
    )
    parser.add_argument(
        "--generate", metavar="PATH", help="write a generated manifest to PATH"
    )
    parser.add_argument(
        "--validate", metavar="PATH", help="validate an existing manifest JSON file"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="return non-zero when any axis is not fully proven",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()

    if args.validate:
        try:
            document = json.loads(Path(args.validate).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"invalid manifest: {exc}", file=sys.stderr)
            return 2
        errors = validate_manifest(document, repo_root)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(document, indent=2, sort_keys=True))
        else:
            print("valid")
        return 0

    document = generate_manifest(repo_root)
    if args.generate:
        _write_json(document, Path(args.generate))
    if args.json or not args.generate:
        print(json.dumps(document, indent=2, sort_keys=True))
    if args.check or args.json:
        return 0 if document["summary"]["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
