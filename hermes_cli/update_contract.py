"""Bounded local staged-update contract.

The current ``simplicio-agent update`` command updates a source checkout (or a
package-managed installation).  This module is the small, local contract that
an installed updater can use later: it validates a manifest, copies a local
directory into a bounded candidate slot, and switches an atomic pointer while
keeping the previous slot available for rollback.

There is deliberately no feed transport, key management, or signature
verification here.  Tests use local temporary directories only; this module
must not be presented as a signed production update feed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Mapping


MANIFEST_SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_FILES = 10_000
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SLOT_NAME = re.compile(r"candidate-[0-9a-f]{32}\Z")
_SLOTS_DIR = "slots"
_ACTIVE_FILE = "active.json"
_STATE_FILE = "update-state.json"
_STAGING_DIR = ".staging"


class ManifestError(ValueError):
    """The update manifest is not safe or internally consistent."""


class UpdateError(RuntimeError):
    """The local update contract cannot complete the requested operation."""


class UpdateInterrupted(UpdateError):
    """Deterministic fault-injection signal used by recovery tests."""


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"manifest {name} must be an integer")
    return value


def _validate_artifact_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError("manifest artifact must be a non-empty relative path")
    if "\x00" in value:
        raise ManifestError("manifest artifact contains a NUL byte")
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or value in {".", ".."}
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ManifestError("manifest artifact must stay within its manifest directory")
    return "/".join(posix.parts)


def _validate_slot_name(value: object) -> str:
    if not isinstance(value, str) or not _SLOT_NAME.fullmatch(value):
        raise UpdateError("slot record contains an invalid slot name")
    return value


@dataclass(frozen=True)
class UpdateManifest:
    """Validated metadata for one local directory artifact."""

    version: str
    artifact: str
    sha256: str
    size_bytes: int
    max_files: int = MAX_FILES
    max_unpacked_bytes: int = MAX_UNPACKED_BYTES
    schema_version: int = MANIFEST_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "UpdateManifest":
        if not isinstance(value, Mapping):
            raise ManifestError("manifest must be a JSON object")
        schema_version = _require_int(value.get("schema_version"), "schema_version")
        if schema_version != MANIFEST_SCHEMA_VERSION:
            raise ManifestError(
                f"unsupported manifest schema_version: {schema_version}"
            )
        version = value.get("version")
        if not isinstance(version, str) or not version.strip() or len(version) > 128:
            raise ManifestError(
                "manifest version must be non-empty and at most 128 characters"
            )
        if any(ord(char) < 0x20 for char in version):
            raise ManifestError("manifest version contains a control character")
        artifact = _validate_artifact_name(value.get("artifact"))
        sha256 = value.get("sha256")
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise ManifestError("manifest sha256 must be a lowercase SHA-256 digest")
        size_bytes = _require_int(value.get("size_bytes"), "size_bytes")
        if not 0 < size_bytes <= MAX_ARTIFACT_BYTES:
            raise ManifestError(
                f"manifest size_bytes must be between 1 and {MAX_ARTIFACT_BYTES}"
            )
        max_files = _require_int(value.get("max_files", MAX_FILES), "max_files")
        max_unpacked_bytes = _require_int(
            value.get("max_unpacked_bytes", MAX_UNPACKED_BYTES),
            "max_unpacked_bytes",
        )
        if not 0 < max_files <= MAX_FILES:
            raise ManifestError(f"manifest max_files must be between 1 and {MAX_FILES}")
        if not 0 < max_unpacked_bytes <= MAX_UNPACKED_BYTES:
            raise ManifestError(
                "manifest max_unpacked_bytes exceeds the contract bound"
            )
        if size_bytes > max_unpacked_bytes:
            raise ManifestError("manifest size_bytes exceeds max_unpacked_bytes")
        return cls(
            version=version.strip(),
            artifact=artifact,
            sha256=sha256,
            size_bytes=size_bytes,
            max_files=max_files,
            max_unpacked_bytes=max_unpacked_bytes,
            schema_version=schema_version,
        )

    @classmethod
    def from_file(cls, path: Path) -> "UpdateManifest":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestError(f"could not read manifest: {exc}") from exc
        return cls.from_dict(raw)


@dataclass(frozen=True)
class ActivationRecord:
    """The durable active/previous slot pair."""

    active_slot: str
    version: str
    previous_slot: str | None = None
    previous_version: str | None = None


@dataclass(frozen=True)
class StagedUpdate:
    """A validated candidate waiting for activation."""

    manifest: UpdateManifest
    slot: str


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        with temp.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"could not read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateError(f"{path.name} must contain a JSON object")
    return value


def _directory_stats(
    root: Path, *, max_files: int, max_bytes: int
) -> tuple[int, int, str]:
    """Return file count, byte count, and a deterministic content digest."""
    if not root.is_dir() or root.is_symlink():
        raise UpdateError("update artifact must be a real directory")
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in directories + files:
            path = current_path / name
            if path.is_symlink():
                raise UpdateError(f"update artifact contains symlink: {path.name}")
        for name in files:
            path = current_path / name
            file_count += 1
            if file_count > max_files:
                raise UpdateError(f"update artifact exceeds {max_files} files")
            size = path.stat().st_size
            total_bytes += size
            if total_bytes > max_bytes:
                raise UpdateError(f"update artifact exceeds {max_bytes} bytes")
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return file_count, total_bytes, digest.hexdigest()


def directory_sha256(root: Path) -> tuple[int, int, str]:
    """Return stats in the same canonical form used by :meth:`stage`."""
    return _directory_stats(
        Path(root), max_files=MAX_FILES, max_bytes=MAX_UNPACKED_BYTES
    )


class UpdateContract:
    """Manage a bounded local A/B-style staged update simulation.

    Only ``root/slots`` and the two JSON control files are managed.  User
    configuration, sessions, databases, models, and ledgers remain outside
    this namespace and are therefore not copied or deleted by this contract.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.slots = self.root / _SLOTS_DIR
        self.active_path = self.root / _ACTIVE_FILE
        self.state_path = self.root / _STATE_FILE
        self.slots.mkdir(parents=True, exist_ok=True)

    def current(self) -> ActivationRecord | None:
        if not self.active_path.exists():
            return None
        value = _read_json(self.active_path)
        active_slot = value.get("active_slot")
        version = value.get("version")
        previous_slot = value.get("previous_slot")
        previous_version = value.get("previous_version")
        if (
            not isinstance(active_slot, str)
            or not active_slot
            or not isinstance(version, str)
            or (previous_slot is not None and not isinstance(previous_slot, str))
            or (previous_version is not None and not isinstance(previous_version, str))
        ):
            raise UpdateError("active.json contains an invalid slot record")
        _validate_slot_name(active_slot)
        if previous_slot is not None:
            _validate_slot_name(previous_slot)
        return ActivationRecord(active_slot, version, previous_slot, previous_version)

    def stage(
        self,
        manifest: UpdateManifest | Path,
        artifact_root: Path | None = None,
    ) -> StagedUpdate:
        """Validate and copy a local directory artifact into a staging area."""
        manifest_path: Path | None = None
        if isinstance(manifest, Path):
            manifest_path = manifest
            manifest = UpdateManifest.from_file(manifest)
            base = manifest_path.parent.resolve()
            artifact_root = (base / manifest.artifact).resolve()
            try:
                if os.path.commonpath((str(base), str(artifact_root))) != str(base):
                    raise ManifestError(
                        "manifest artifact escapes its manifest directory"
                    )
            except ValueError as exc:
                raise ManifestError(
                    "manifest artifact is on a different volume"
                ) from exc
        if artifact_root is None:
            raise ManifestError("artifact_root is required for an in-memory manifest")
        if self.state_path.exists():
            self.recover_interrupted()
        source = Path(artifact_root)
        file_count, total_bytes, digest = _directory_stats(
            source,
            max_files=manifest.max_files,
            max_bytes=manifest.max_unpacked_bytes,
        )
        if file_count == 0 or total_bytes != manifest.size_bytes:
            raise ManifestError("artifact size does not match manifest")
        if digest != manifest.sha256:
            raise ManifestError("artifact SHA-256 does not match manifest")
        shutil.rmtree(self.slots / _STAGING_DIR, ignore_errors=True)
        staging = self.slots / _STAGING_DIR
        try:
            self._copy_bounded(source, staging, manifest)
            copied_files, copied_bytes, copied_digest = _directory_stats(
                staging,
                max_files=manifest.max_files,
                max_bytes=manifest.max_unpacked_bytes,
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        if (
            copied_files != file_count
            or copied_bytes != manifest.size_bytes
            or copied_digest != manifest.sha256
        ):
            shutil.rmtree(staging, ignore_errors=True)
            raise ManifestError("staged artifact changed while it was being copied")
        slot = f"candidate-{uuid.uuid4().hex}"
        self._write_state({
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "phase": "staged",
            "slot": slot,
            "version": manifest.version,
        })
        return StagedUpdate(manifest, slot)

    def activate(
        self,
        staged: StagedUpdate,
        *,
        health_check: Callable[[Path], bool] | None = None,
        interrupt_after: str | None = None,
    ) -> ActivationRecord:
        """Atomically activate a staged candidate and retain the old slot.

        ``interrupt_after`` is a deterministic test seam.  It simulates a
        process stop at a durable boundary and is not a production setting.
        """
        state = self._pending_state()
        if (
            state.get("slot") != staged.slot
            or state.get("version") != staged.manifest.version
        ):
            raise UpdateError("staged update is not the pending candidate")
        old = self.current()
        staging = self.slots / _STAGING_DIR
        candidate = self.slots / staged.slot
        if not staging.is_dir():
            raise UpdateError("staged artifact is missing")
        if candidate.exists():
            shutil.rmtree(candidate)
        os.replace(staging, candidate)
        self._write_state({
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "phase": "activating",
            "slot": staged.slot,
            "version": staged.manifest.version,
            "old_active_slot": old.active_slot if old else None,
            "old_active_version": old.version if old else None,
            "old_previous_slot": old.previous_slot if old else None,
        })
        if interrupt_after == "state":
            raise UpdateInterrupted("interrupted after activation state")
        record = ActivationRecord(
            staged.slot,
            staged.manifest.version,
            old.active_slot if old else None,
            old.version if old else None,
        )
        self._write_active(record)
        if interrupt_after == "pointer":
            raise UpdateInterrupted("interrupted after active pointer")
        if health_check is not None:
            try:
                healthy = health_check(candidate)
            except Exception as exc:
                healthy = False
                health_error = exc
            else:
                health_error = None
            if not healthy:
                self.rollback()
                detail = f": {health_error}" if health_error else ""
                raise UpdateError(f"candidate health check failed; rolled back{detail}")
        self._write_state({
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "phase": "committed",
            "slot": record.active_slot,
            "version": record.version,
        })
        if interrupt_after == "commit":
            raise UpdateInterrupted("interrupted after commit state")
        self._finish_commit(record)
        return record

    def rollback(self) -> ActivationRecord:
        """Switch back to the preserved previous slot, if one exists."""
        if self.state_path.exists():
            self.recover_interrupted()
        current = self.current()
        if current is None or current.previous_slot is None:
            raise UpdateError("no previous slot is available for rollback")
        previous_path = self.slots / current.previous_slot
        if not previous_path.is_dir():
            raise UpdateError("previous slot is missing; refusing destructive rollback")
        record = ActivationRecord(
            current.previous_slot,
            current.previous_version or self._slot_version(previous_path),
            current.active_slot,
            current.version,
        )
        self._write_active(record)
        self._write_state({
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "phase": "committed",
            "slot": record.active_slot,
            "version": record.version,
        })
        self._finish_commit(record)
        return record

    def recover_interrupted(self) -> ActivationRecord | None:
        """Recover a stop at any durable boundary; safe to call repeatedly."""
        self._remove_control_temps()
        if not self.state_path.exists():
            shutil.rmtree(self.slots / _STAGING_DIR, ignore_errors=True)
            return self.current()
        state = self._pending_state()
        phase = state.get("phase")
        slot = state.get("slot")
        if not isinstance(slot, str) or not slot:
            raise UpdateError("update state contains an invalid candidate slot")
        _validate_slot_name(slot)
        if phase == "staged":
            shutil.rmtree(self.slots / _STAGING_DIR, ignore_errors=True)
            shutil.rmtree(self.slots / slot, ignore_errors=True)
            self.state_path.unlink(missing_ok=True)
            return self.current()
        if phase == "activating":
            current = self.current()
            if current is not None and current.active_slot == slot:
                committed = ActivationRecord(
                    slot,
                    str(state.get("version", current.version)),
                    str(state["old_active_slot"])
                    if state.get("old_active_slot")
                    else None,
                    str(state["old_active_version"])
                    if state.get("old_active_version")
                    else None,
                )
                self._write_active(committed)
                self._finish_commit(committed)
                return committed
            shutil.rmtree(self.slots / slot, ignore_errors=True)
            self.state_path.unlink(missing_ok=True)
            return current
        if phase == "committed":
            current = self.current()
            if current is None:
                raise UpdateError("committed update has no active pointer")
            self._finish_commit(current)
            return current
        raise UpdateError(f"unknown update phase: {phase!r}")

    def _copy_bounded(
        self, source: Path, target: Path, manifest: UpdateManifest
    ) -> None:
        target.mkdir(parents=True)
        for current, directories, files in os.walk(source, followlinks=False):
            relative = Path(current).relative_to(source)
            destination = target / relative
            destination.mkdir(parents=True, exist_ok=True)
            directories.sort()
            files.sort()
            for name in directories + files:
                if (Path(current) / name).is_symlink():
                    raise UpdateError(f"update artifact contains symlink: {name}")
            for name in files:
                shutil.copy2(Path(current) / name, destination / name)
        _directory_stats(
            target, max_files=manifest.max_files, max_bytes=manifest.max_unpacked_bytes
        )

    def _pending_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            raise UpdateError("no staged update is pending")
        return _read_json(self.state_path)

    def _write_state(self, value: Mapping[str, object]) -> None:
        _atomic_write_json(self.state_path, value)

    def _write_active(self, record: ActivationRecord) -> None:
        _atomic_write_json(
            self.active_path,
            {
                "active_slot": record.active_slot,
                "version": record.version,
                "previous_slot": record.previous_slot,
                "previous_version": record.previous_version,
            },
        )

    def _finish_commit(self, record: ActivationRecord) -> None:
        keep = {record.active_slot}
        if record.previous_slot:
            keep.add(record.previous_slot)
        for child in self.slots.iterdir():
            if child.name == _STAGING_DIR or child.name.startswith("candidate-"):
                if child.name not in keep:
                    shutil.rmtree(child, ignore_errors=True)
        self.state_path.unlink(missing_ok=True)

    def _remove_control_temps(self) -> None:
        for path in self.root.glob(".*.tmp"):
            path.unlink(missing_ok=True)

    def _slot_version(self, slot: Path) -> str:
        for child in slot.iterdir():
            if child.is_file() and child.name == "VERSION":
                return child.read_text(encoding="utf-8").strip()
        return "unknown"


__all__ = [
    "ActivationRecord",
    "ManifestError",
    "MAX_ARTIFACT_BYTES",
    "MAX_FILES",
    "MAX_UNPACKED_BYTES",
    "StagedUpdate",
    "UpdateContract",
    "UpdateError",
    "UpdateInterrupted",
    "UpdateManifest",
    "directory_sha256",
]
