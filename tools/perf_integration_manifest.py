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
    "PACKAGED",
    "INSTALLED",
    "INVOKED",
    "E2E",
    "DEFAULT",
    "GATED",
)
PASSING_STATUSES = frozenset(("pass", "not_applicable"))
VALID_STATUSES = frozenset(("pass", "fail", "not_applicable", "unknown"))


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
    source: tuple[str, ...]
    call_sites: tuple[dict[str, str], ...]
    config: tuple[dict[str, str], ...]
    fallback: dict[str, Any]
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
        }


@dataclass(frozen=True)
class AxisSpec:
    name: str
    description: str
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
        source=spec.source,
        call_sites=spec.call_sites,
        config=spec.config,
        fallback=dict(spec.fallback),
    )


def _check_uvloop(result: AxisResult, repo_root: Path) -> None:
    present = all((repo_root / path).is_file() for path in result.source)
    result.mark("PRESENT", present, evidence=result.source)
    source_ok = present and _contains(
        repo_root, "agent/uvloop_utils.py", "def install_uvloop_policy"
    )
    result.mark(
        "SAME_SOURCE",
        source_ok,
        evidence=("agent/uvloop_utils.py:install_uvloop_policy",),
    )
    built = _importable("agent.uvloop_utils", repo_root)
    result.mark("BUILT", built, evidence=("agent.uvloop_utils",))
    pyproject = _text(repo_root, "pyproject.toml")
    result.mark(
        "PACKAGED",
        '"uvloop>=' in pyproject and "sys_platform != 'win32'" in pyproject,
        evidence=("pyproject.toml:project.optional-dependencies.fast",),
    )

    available = _importable("uvloop", repo_root)
    platform_skip = sys.platform == "win32"
    if platform_skip:
        result.mark(
            "INSTALLED",
            status="not_applicable",
            reason="uvloop is not supported on Windows",
        )
    else:
        result.mark(
            "INSTALLED",
            available,
            reason="uvloop importable" if available else "uvloop is unavailable",
        )

    invoked = False
    if platform_skip:
        result.mark(
            "INVOKED",
            status="not_applicable",
            reason="asyncio fallback is the Windows path",
        )
    elif available and built:
        try:
            old_policy = asyncio.get_event_loop_policy()
            module = importlib.import_module("agent.uvloop_utils")
            invoked = bool(module.install_uvloop_policy())
            asyncio.set_event_loop_policy(old_policy)
        except Exception:
            invoked = False
        result.mark(
            "INVOKED", invoked, evidence=("agent.uvloop_utils:install_uvloop_policy",)
        )
    else:
        result.mark("INVOKED", False, reason="uvloop activation cannot be exercised")

    e2e = all(
        _contains(repo_root, call["path"], call["symbol"]) for call in result.call_sites
    )
    result.mark(
        "E2E",
        e2e,
        evidence=tuple(f"{c['path']}:{c['symbol']}" for c in result.call_sites),
    )
    result.mark(
        "DEFAULT",
        "strongly recommended" in pyproject or "recommended" in pyproject,
        evidence=("pyproject.toml:fast",),
    )
    result.mark(
        "GATED",
        _contains(repo_root, "hermes_cli/doctor.py", "uvloop event loop"),
        evidence=("hermes_cli/doctor.py:uvloop event loop",),
    )


def _check_fast_json(result: AxisResult, repo_root: Path) -> None:
    present = all((repo_root / path).is_file() for path in result.source)
    result.mark("PRESENT", present, evidence=result.source)
    source_ok = present and _contains(
        repo_root, "agent/serde/fast_json.py", "def has_msgspec"
    )
    result.mark(
        "SAME_SOURCE", source_ok, evidence=("agent/serde/fast_json.py:has_msgspec",)
    )
    built = _importable("agent.serde.fast_json", repo_root)
    result.mark("BUILT", built, evidence=("agent.serde.fast_json",))
    pyproject = _text(repo_root, "pyproject.toml")
    packaged = all(token in pyproject for token in ("orjson>=", "msgspec>="))
    result.mark(
        "PACKAGED",
        packaged,
        evidence=("pyproject.toml:project.optional-dependencies.fast",),
    )
    has_orjson = _module_attr(
        "agent.serde.fast_json", "has_orjson", repo_root
    ) and _importable("orjson", repo_root)
    has_msgspec = _module_attr(
        "agent.serde.fast_json", "has_msgspec", repo_root
    ) and _importable("msgspec", repo_root)
    result.mark(
        "INSTALLED",
        has_orjson or has_msgspec,
        reason=f"orjson={has_orjson} msgspec={has_msgspec}",
    )
    invoked, receipt = (
        _exercise_fast_json(repo_root)
        if built
        else (
            False,
            "serializer module is not importable",
        )
    )
    result.mark(
        "INVOKED",
        invoked and (has_orjson or has_msgspec),
        reason=receipt,
        evidence=("agent.serde.fast_json:dumps/loads",),
    )
    e2e = all(
        _contains(repo_root, call["path"], call["symbol"]) for call in result.call_sites
    )
    result.mark(
        "E2E",
        e2e,
        evidence=tuple(f"{c['path']}:{c['symbol']}" for c in result.call_sites),
    )
    result.mark(
        "DEFAULT",
        "strongly recommended" in pyproject or "recommended" in pyproject,
        evidence=("pyproject.toml:fast",),
    )
    result.mark(
        "GATED",
        _contains(repo_root, "hermes_cli/doctor.py", "Fast JSON"),
        evidence=("hermes_cli/doctor.py:Fast JSON",),
    )


def _check_prewarm(result: AxisResult, repo_root: Path) -> None:
    present = all((repo_root / path).is_file() for path in result.source)
    result.mark("PRESENT", present, evidence=result.source)
    source_ok = present and all(
        _contains(repo_root, call["path"], f"def {call['symbol']}")
        for call in result.call_sites
    )
    result.mark(
        "SAME_SOURCE",
        source_ok,
        evidence=tuple(f"{c['path']}:{c['symbol']}" for c in result.call_sites),
    )
    built = _importable("agent.skill_commands", repo_root) and _importable(
        "hermes_cli.model_switch", repo_root
    )
    result.mark(
        "BUILT", built, evidence=("agent.skill_commands", "hermes_cli.model_switch")
    )
    config = _text(repo_root, "hermes_cli/config.py")
    packaged = all(item["key"] in config for item in result.config)
    result.mark(
        "PACKAGED",
        packaged,
        evidence=tuple(f"{c['path']}:{c['key']}" for c in result.config),
    )
    installed = _module_attr(
        "agent.skill_commands", "prewarm_skill_payloads", repo_root
    ) and _module_attr(
        "hermes_cli.model_switch", "prewarm_picker_cache_async", repo_root
    )
    result.mark(
        "INSTALLED",
        installed,
        evidence=("prewarm_skill_payloads", "prewarm_picker_cache_async"),
    )
    invoked = _contains(repo_root, "hermes_cli/model_switch.py", "_picker_prewarm_done")
    result.mark(
        "INVOKED",
        invoked,
        evidence=("hermes_cli/model_switch.py:_picker_prewarm_done",),
    )
    e2e = _contains(repo_root, "agent/agent_init.py", "_openrouter_prewarm_done")
    result.mark("E2E", e2e, evidence=("agent/agent_init.py:_openrouter_prewarm_done",))
    result.mark(
        "DEFAULT",
        all(item["key"] in config for item in result.config),
        evidence=tuple(f"{c['path']}:{c['key']}" for c in result.config),
    )
    result.mark(
        "GATED", "prewarm" in config.lower(), evidence=("hermes_cli/config.py:prewarm",)
    )


AXIS_SPECS: tuple[AxisSpec, ...] = (
    AxisSpec(
        "uvloop",
        "Optional libuv event-loop policy for async entrypoints.",
        ("agent/uvloop_utils.py", "agent/async_dag/uvloop_runner.py"),
        (
            {"path": "hermes_cli/main.py", "symbol": "install_uvloop_policy()"},
            {"path": "hermes_cli/gateway.py", "symbol": "install_uvloop_policy()"},
        ),
        ({"path": "pyproject.toml", "key": "fast.uvloop"},),
        {
            "available": True,
            "paths": ["agent/uvloop_utils.py"],
            "description": "asyncio default policy",
        },
        _check_uvloop,
    ),
    AxisSpec(
        "fast-json",
        "Fast JSON serialization with msgspec/orjson and stdlib fallback.",
        ("agent/serde/fast_json.py", "agent/serde/__init__.py", "agent/_fastjson.py"),
        (
            {"path": "run_agent.py", "symbol": "from agent._fastjson"},
            {"path": "agent/telemetry/receipts.py", "symbol": "from agent.serde"},
        ),
        (
            {"path": "pyproject.toml", "key": "fast.orjson"},
            {"path": "pyproject.toml", "key": "fast.msgspec"},
        ),
        {
            "available": True,
            "paths": ["agent/_fastjson.py"],
            "description": "stdlib json",
        },
        _check_fast_json,
    ),
    AxisSpec(
        "prewarm",
        "Bounded background prewarm for skills and model picker caches.",
        (
            "agent/skill_commands.py",
            "hermes_cli/model_switch.py",
            "agent/agent_init.py",
        ),
        (
            {"path": "agent/skill_commands.py", "symbol": "prewarm_skill_payloads"},
            {
                "path": "hermes_cli/model_switch.py",
                "symbol": "prewarm_picker_cache_async",
            },
        ),
        (
            {"path": "hermes_cli/config.py", "key": "prewarm_max_items"},
            {"path": "hermes_cli/config.py", "key": "prewarm_cache_max_entries"},
        ),
        {
            "available": True,
            "paths": ["agent/skill_commands.py"],
            "description": "bounded no-op on errors",
        },
        _check_prewarm,
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
    return 0 if document["summary"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
