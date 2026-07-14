"""Staging validation, atomic ``current`` activation, and restart intent.

This module is the bounded Native 2.3 boundary.  It deliberately does not
discover installations, preserve dirty trees, fetch remotes, or own update
leases.  Those concerns belong to the preceding updater slices.  A caller
hands this module an already-prepared staging directory and receives either a
per-gate receipt or a fail-closed result; only a validated directory can be
copied into a slot and published through the atomic ``current`` record.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


VALIDATION_SCHEMA = "simplicio.staging-validation/v1"
POINTER_SCHEMA = "simplicio.current-pointer/v1"
RESTART_INTENT_SCHEMA = "simplicio.detached-restart/v1"
DEFAULT_LOCKFILES = ("uv.lock", "runtime.lock", "Cargo.lock")


class GateName(str, Enum):
    SYNTAX = "syntax"
    IMPORT = "import"
    CONFIG = "config"
    FOCUSED_SMOKE = "focused_smoke"


@dataclass(frozen=True)
class GateReceipt:
    """The independent result and log for one staging gate."""

    name: GateName
    passed: bool
    detail: str
    duration_ms: float
    log_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name.value,
            "passed": self.passed,
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 3),
            "log_path": self.log_path,
        }


@dataclass(frozen=True)
class StagingValidation:
    """All four staging gate receipts and the resulting content digest."""

    staging: Path
    gates: tuple[GateReceipt, ...]
    digest: str | None

    @property
    def passed(self) -> bool:
        return len(self.gates) == len(GateName) and all(
            gate.passed for gate in self.gates
        )

    def receipt(self) -> dict[str, object]:
        return {
            "schema": VALIDATION_SCHEMA,
            "staging": str(self.staging),
            "passed": self.passed,
            "digest": self.digest,
            "gates": [gate.to_dict() for gate in self.gates],
        }


class StagingValidationError(RuntimeError):
    """Raised when activation is attempted without four passing gates."""


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _directory_digest(root: Path) -> str:
    """Hash relative names and bytes, rejecting symlinks in the candidate."""

    if not root.is_dir() or root.is_symlink():
        raise ValueError("staging must be a real directory")
    digest = hashlib.sha256()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in directories + files:
            path = current_path / name
            if path.is_symlink():
                raise ValueError(f"staging contains symlink: {path}")
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _write_log(log_dir: Path | None, gate: GateName, text: str) -> str | None:
    if log_dir is None:
        return None
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{gate.value}.log"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return str(path)


def _gate(
    name: GateName,
    operation: Callable[[], str],
    *,
    log_dir: Path | None,
) -> GateReceipt:
    started = time.perf_counter()
    try:
        detail = operation()
    except Exception as exc:  # each gate is independently reportable
        detail = f"{type(exc).__name__}: {exc}"
        passed = False
    else:
        passed = True
    return GateReceipt(
        name=name,
        passed=passed,
        detail=detail,
        duration_ms=(time.perf_counter() - started) * 1000,
        log_path=_write_log(log_dir, name, detail),
    )


def _syntax_gate(staging: Path, touched_files: Sequence[str] | None) -> str:
    paths = (
        [staging / rel for rel in touched_files]
        if touched_files is not None
        else sorted(staging.rglob("*.py"))
    )
    checked = 0
    for path in paths:
        if not _inside(staging, path):
            raise ValueError(f"touched file escapes staging: {path}")
        if not path.is_file():
            continue
        compile(path.read_bytes(), str(path), "exec")
        checked += 1
    return f"parsed {checked} Python files"


def _import_gate(staging: Path, entrypoints: Sequence[str]) -> str:
    if not entrypoints:
        raise ValueError("at least one staging entrypoint is required")
    code = (
        "import importlib, sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "[importlib.import_module(name) for name in sys.argv[2:]]"
    )
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
    }
    if os.name == "nt" and os.environ.get("SystemRoot"):
        environment["SystemRoot"] = os.environ["SystemRoot"]
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(staging), *entrypoints],
        cwd=staging,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return f"imported {len(entrypoints)} staging entrypoints in a clean interpreter"


def _load_config(path: Path) -> object:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to validate YAML config") from exc
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _config_gate(
    staging: Path,
    config_paths: Sequence[str],
    config_validator: Callable[[Path, object], object] | None,
) -> str:
    if config_validator is None:
        from hermes_cli.config import validate_config_structure

        def config_validator(path: Path, value: object) -> object:
            if not isinstance(value, dict):
                return [f"{path.name} root must be a mapping"]
            return [
                issue.message
                for issue in validate_config_structure(value)
                if issue.severity == "error"
            ]

    paths = [staging / rel for rel in config_paths]
    checked = 0
    for path in paths:
        if not _inside(staging, path):
            raise ValueError(f"config path escapes staging: {path}")
        if not path.is_file():
            continue
        value = _load_config(path)
        if config_validator is not None:
            result = config_validator(path, value)
            if result is False:
                raise ValueError(f"config schema rejected {path}")
            if isinstance(result, Iterable) and not isinstance(
                result, (str, bytes, dict)
            ):
                errors = list(result)
                if errors:
                    raise ValueError("; ".join(str(error) for error in errors))
        checked += 1
    return f"validated {checked} staged config files against the schema registry"


def validate_staging(
    staging: str | Path,
    *,
    touched_files: Sequence[str] | None = None,
    entrypoints: Sequence[str] = ("hermes_cli.config",),
    config_paths: Sequence[str] = ("config.yaml", "config.yml", "config.json"),
    config_validator: Callable[[Path, object], object] | None = None,
    focused_smoke: Callable[[Path], object] | None = None,
    log_dir: str | Path | None = None,
) -> StagingValidation:
    """Run syntax, clean-import, config, and focused-smoke gates in staging.

    The active checkout is never imported or written by this function.  The
    smoke callback is deliberately required; passing ``None`` is a visible
    failed gate rather than an accidental claim that a smoke test ran.
    """

    root = Path(staging).resolve()
    logs = Path(log_dir) if log_dir is not None else None
    gates = [
        _gate(
            GateName.SYNTAX,
            lambda: _syntax_gate(root, touched_files),
            log_dir=logs,
        ),
        _gate(
            GateName.IMPORT,
            lambda: _import_gate(root, entrypoints),
            log_dir=logs,
        ),
        _gate(
            GateName.CONFIG,
            lambda: _config_gate(root, config_paths, config_validator),
            log_dir=logs,
        ),
    ]

    def smoke() -> str:
        if focused_smoke is None:
            raise ValueError("focused smoke runner is required")
        result = focused_smoke(root)
        if result is False:
            raise RuntimeError("focused smoke fixture returned false")
        return "focused smoke fixture passed"

    gates.append(_gate(GateName.FOCUSED_SMOKE, smoke, log_dir=logs))
    digest = None
    if all(gate.passed for gate in gates):
        try:
            digest = _directory_digest(root)
        except Exception:
            digest = None
    return StagingValidation(root, tuple(gates), digest)


def _lock_digest(root: Path, lockfiles: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(lockfiles):
        path = root / relative
        if not _inside(root, path):
            raise ValueError(f"lockfile escapes root: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class LockSyncDecision:
    """Digest-only decision; executing a package manager is out of scope."""

    staging_digest: str
    active_digest: str
    changed: bool
    lockfiles: tuple[str, ...]

    @property
    def should_sync(self) -> bool:
        return self.changed

    def to_dict(self) -> dict[str, object]:
        return {
            "staging_digest": self.staging_digest,
            "active_digest": self.active_digest,
            "changed": self.changed,
            "should_sync": self.should_sync,
            "lockfiles": list(self.lockfiles),
        }


def decide_lock_sync(
    staging: str | Path,
    active: str | Path,
    *,
    lockfiles: Sequence[str] = DEFAULT_LOCKFILES,
) -> LockSyncDecision:
    """Compare only lockfile digests; identical locks require zero sync work."""

    names = tuple(sorted(dict.fromkeys(lockfiles)))
    staging_digest = _lock_digest(Path(staging).resolve(), names)
    active_digest = _lock_digest(Path(active).resolve(), names)
    return LockSyncDecision(
        staging_digest, active_digest, staging_digest != active_digest, names
    )


@dataclass(frozen=True)
class PointerRecord:
    slot: str
    digest: str
    schema: str = POINTER_SCHEMA

    def to_dict(self) -> dict[str, str]:
        return {"schema": self.schema, "slot": self.slot, "digest": self.digest}


def _atomic_write(path: Path, payload: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


class AtomicCurrentPointer:
    """Publish complete slots through an atomically replaced ``current`` file."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.slots = self.root / "slots"
        self.path = self.root / "current"
        self.slots.mkdir(parents=True, exist_ok=True)

    def read(self) -> PointerRecord | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("pointer must be a JSON object")
            record = PointerRecord(
                schema=value["schema"], slot=value["slot"], digest=value["digest"]
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StagingValidationError(f"invalid current pointer: {exc}") from exc
        if (
            record.schema != POINTER_SCHEMA
            or not isinstance(record.slot, str)
            or not isinstance(record.digest, str)
        ):
            raise StagingValidationError("current pointer has invalid fields")
        slot = self.slots / record.slot
        if not _inside(self.slots, slot):
            raise StagingValidationError("current pointer slot escapes slots directory")
        if not slot.is_dir() or _directory_digest(slot) != record.digest:
            raise StagingValidationError(
                "current pointer target failed digest verification"
            )
        return record

    def activate(
        self,
        staging: str | Path,
        *,
        validation: StagingValidation | None = None,
    ) -> PointerRecord:
        """Copy a validated staging tree to a new slot, then publish ``current``."""

        source = Path(staging).resolve()
        if validation is None:
            raise StagingValidationError(
                "activation requires a staging validation receipt"
            )
        if validation.staging.resolve() != source or not validation.passed:
            raise StagingValidationError("staging gates did not all pass")
        if validation.digest is None:
            raise StagingValidationError("validated staging has no content digest")
        if _directory_digest(source) != validation.digest:
            raise StagingValidationError("staging changed after validation")
        slot_name = f"slot-{uuid.uuid4().hex}"
        temporary = self.slots / f".{slot_name}.tmp"
        final = self.slots / slot_name
        try:
            shutil.copytree(source, temporary, symlinks=False)
            if _directory_digest(temporary) != validation.digest:
                raise StagingValidationError("copied slot failed digest verification")
            # ``os.replace`` is atomic for files but rejects directory
            # destinations on Windows.  The final slot is guaranteed absent,
            # so the platform rename is the atomic directory publication.
            temporary.rename(final)
            record = PointerRecord(slot_name, validation.digest)
            _atomic_write(
                self.path,
                json.dumps(record.to_dict(), sort_keys=True) + "\n",
            )
            return record
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    activate_staging = activate


CurrentPointer = AtomicCurrentPointer


@dataclass(frozen=True)
class DetachedRestartIntent:
    """Durable input to a helper that outlives the active process."""

    old_pid: int
    target_slot: str
    pointer_digest: str
    supervisor: str
    drain_timeout_s: float = 30.0
    startup_timeout_s: float = 60.0
    schema: str = RESTART_INTENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RESTART_INTENT_SCHEMA:
            raise ValueError(f"unsupported restart intent schema: {self.schema!r}")
        if self.old_pid <= 0 or not self.target_slot or not self.pointer_digest:
            raise ValueError(
                "restart intent requires pid, target slot, and pointer digest"
            )
        if self.drain_timeout_s < 0 or self.startup_timeout_s < 0:
            raise ValueError("restart timeouts must be non-negative")
        if not self.supervisor:
            raise ValueError("restart intent requires a supervisor")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "old_pid": self.old_pid,
            "target_slot": self.target_slot,
            "pointer_digest": self.pointer_digest,
            "supervisor": self.supervisor,
            "drain_timeout_s": self.drain_timeout_s,
            "startup_timeout_s": self.startup_timeout_s,
        }

    def write(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(destination, json.dumps(self.to_dict(), sort_keys=True) + "\n")
        return destination


class RestartPhase(str, Enum):
    PREPARED = "prepared"
    DRAINED = "drained"
    REQUESTED = "requested"
    STARTED = "started"
    FAILED = "failed"


@dataclass(frozen=True)
class RestartResult:
    phase: RestartPhase
    detail: str
    intent: DetachedRestartIntent


class DetachedRestartHelper:
    """Spawn and run the supervisor restart boundary without self-termination."""

    def __init__(self, intent: DetachedRestartIntent) -> None:
        self.intent = intent

    def launch(
        self,
        command: Sequence[str],
        intent_path: str | Path,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> Any:
        """Persist intent and spawn a new session; caller remains alive."""

        self.intent.write(intent_path)
        kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ) | getattr(subprocess, "DETACHED_PROCESS", 0)
        else:
            kwargs["start_new_session"] = True
        return popen(list(command), **kwargs)

    def run(
        self,
        *,
        wait_for_drain: Callable[[float], bool],
        request_supervisor_restart: Callable[[DetachedRestartIntent], bool],
        wait_for_startup: Callable[[DetachedRestartIntent, float], bool],
    ) -> RestartResult:
        """Execute the helper state machine; no callback may terminate the old process."""

        if not wait_for_drain(self.intent.drain_timeout_s):
            return RestartResult(
                RestartPhase.FAILED, "drain did not complete", self.intent
            )
        if not request_supervisor_restart(self.intent):
            return RestartResult(
                RestartPhase.FAILED, "supervisor rejected restart", self.intent
            )
        if not wait_for_startup(self.intent, self.intent.startup_timeout_s):
            return RestartResult(
                RestartPhase.FAILED, "new process did not become healthy", self.intent
            )
        return RestartResult(
            RestartPhase.STARTED, "supervisor restart completed", self.intent
        )


__all__ = [
    "VALIDATION_SCHEMA",
    "POINTER_SCHEMA",
    "RESTART_INTENT_SCHEMA",
    "DEFAULT_LOCKFILES",
    "GateName",
    "GateReceipt",
    "StagingValidation",
    "StagingValidationError",
    "validate_staging",
    "LockSyncDecision",
    "decide_lock_sync",
    "PointerRecord",
    "AtomicCurrentPointer",
    "CurrentPointer",
    "DetachedRestartIntent",
    "RestartPhase",
    "RestartResult",
    "DetachedRestartHelper",
]
