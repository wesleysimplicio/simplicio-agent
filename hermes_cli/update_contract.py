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
from typing import Callable, Iterable, Mapping

from tools.runtime_lock_contract import is_strict_semver


MANIFEST_SCHEMA_VERSION = 1
COMPATIBILITY_SCHEMA = "simplicio.update-compatibility/v2"
COMPATIBILITY_VERSION = 2
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_FILES = 10_000
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SLOT_NAME = re.compile(r"candidate-[0-9a-f]{32}\Z")
_MIGRATION_ID = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*\Z")
_EFFECT_NAME = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*\Z")
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


def _require_string_list(
    value: object,
    name: str,
    *,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise UpdateError(f"{name} must be a list of strings")
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise UpdateError(f"{name} must contain only non-empty strings")
        normalized = item.strip()
        if pattern is not None and not pattern.fullmatch(normalized):
            raise UpdateError(f"{name} contains an invalid value: {normalized!r}")
        if normalized not in seen:
            seen.add(normalized)
            items.append(normalized)
    return tuple(items)


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
    applied_migrations: tuple[str, ...] = ()
    previous_applied_migrations: tuple[str, ...] = ()
    rollback_migration_ids: tuple[str, ...] = ()
    previous_rollback_migration_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompatibilityRule:
    """One exact version transition and its migration gates."""

    from_version: str | None
    to_version: str
    supported: bool
    migration_ids: tuple[str, ...] = ()
    blocked_effects: tuple[str, ...] = ()
    notes: str = ""
    rollback_migration_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.from_version is not None and not is_strict_semver(self.from_version):
            raise UpdateError("compatibility from_version must be strict semver or null")
        if not is_strict_semver(self.to_version):
            raise UpdateError("compatibility to_version must be strict semver")
        for migration_id in self.migration_ids:
            if not _MIGRATION_ID.fullmatch(migration_id):
                raise UpdateError(
                    f"compatibility migration id is invalid: {migration_id!r}"
                )
        for migration_id in self.rollback_migration_ids:
            if not _MIGRATION_ID.fullmatch(migration_id):
                raise UpdateError(
                    "compatibility rollback migration id is invalid: "
                    f"{migration_id!r}"
                )
        for effect in self.blocked_effects:
            if not _EFFECT_NAME.fullmatch(effect):
                raise UpdateError(
                    f"compatibility blocked effect is invalid: {effect!r}"
                )
        if not self.supported and (
            self.migration_ids or self.rollback_migration_ids
        ):
            raise UpdateError("unsupported transitions cannot declare migrations")
        if self.rollback_migration_ids and (
            len(self.rollback_migration_ids) != len(self.migration_ids)
        ):
            raise UpdateError(
                "compatibility rollback migrations must map one-to-one to migrations"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "supported": self.supported,
            "migration_ids": list(self.migration_ids),
            "rollback_migration_ids": list(self.rollback_migration_ids),
            "blocked_effects": list(self.blocked_effects),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CompatibilityMatrix:
    """Machine-readable authority for update and downgrade transitions."""

    schema: str
    version: int
    rows: tuple[CompatibilityRule, ...]

    def __post_init__(self) -> None:
        if self.schema != COMPATIBILITY_SCHEMA:
            raise UpdateError(f"unsupported compatibility schema: {self.schema!r}")
        if self.version != COMPATIBILITY_VERSION:
            raise UpdateError(
                f"unsupported compatibility version: {self.version!r}"
            )
        seen: set[tuple[str | None, str]] = set()
        for row in self.rows:
            key = (row.from_version, row.to_version)
            if key in seen:
                raise UpdateError("compatibility rows must be unique per transition")
            seen.add(key)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CompatibilityMatrix":
        if not isinstance(value, Mapping):
            raise UpdateError("compatibility matrix must be a JSON object")
        rows_value = value.get("rows")
        if not isinstance(rows_value, list):
            raise UpdateError("compatibility rows must be a list")
        rows: list[CompatibilityRule] = []
        for item in rows_value:
            if not isinstance(item, Mapping):
                raise UpdateError("compatibility rows must contain only objects")
            from_version = item.get("from_version")
            if from_version is not None and not isinstance(from_version, str):
                raise UpdateError("compatibility from_version must be a string or null")
            to_version = item.get("to_version")
            if not isinstance(to_version, str):
                raise UpdateError("compatibility to_version must be a string")
            supported = item.get("supported")
            if not isinstance(supported, bool):
                raise UpdateError("compatibility supported must be a boolean")
            notes = item.get("notes", "")
            if not isinstance(notes, str):
                raise UpdateError("compatibility notes must be a string")
            rows.append(
                CompatibilityRule(
                    from_version=from_version,
                    to_version=to_version,
                    supported=supported,
                    migration_ids=_require_string_list(
                        item.get("migration_ids", []),
                        "compatibility migration_ids",
                        pattern=_MIGRATION_ID,
                    ),
                    rollback_migration_ids=_require_string_list(
                        item.get("rollback_migration_ids", []),
                        "compatibility rollback_migration_ids",
                        pattern=_MIGRATION_ID,
                    ),
                    blocked_effects=_require_string_list(
                        item.get("blocked_effects", []),
                        "compatibility blocked_effects",
                        pattern=_EFFECT_NAME,
                    ),
                    notes=notes,
                )
            )
        version = value.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise UpdateError("compatibility version must be an integer")
        return cls(
            schema=str(value.get("schema", "")),
            version=version,
            rows=tuple(rows),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "rows": [row.to_dict() for row in self.rows],
        }

    def transition(
        self, current_version: str | None, target_version: str
    ) -> CompatibilityRule | None:
        return next(
            (
                row
                for row in self.rows
                if row.from_version == current_version and row.to_version == target_version
            ),
            None,
        )


@dataclass(frozen=True)
class UpdatePlan:
    """Deterministic validation result for one update transition."""

    current_version: str | None
    target_version: str
    direction: str
    allowed: bool
    migration_ids: tuple[str, ...]
    blocked_effects: tuple[str, ...]
    rollback_available: bool
    reason: str
    notes: str = ""
    rollback_migration_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.allowed and self.migration_ids and (
            len(self.rollback_migration_ids) != len(self.migration_ids)
        ):
            raise UpdateError(
                "allowed migration plans require one-to-one rollback migrations"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "current_version": self.current_version,
            "target_version": self.target_version,
            "direction": self.direction,
            "allowed": self.allowed,
            "migration_ids": list(self.migration_ids),
            "rollback_migration_ids": list(self.rollback_migration_ids),
            "blocked_effects": list(self.blocked_effects),
            "rollback_available": self.rollback_available,
            "reason": self.reason,
            "notes": self.notes,
        }


def _build_update_plan(
    current: ActivationRecord | None,
    manifest: UpdateManifest,
    matrix: CompatibilityMatrix,
    *,
    in_flight_effects: Iterable[str] = (),
) -> UpdatePlan:
    """Build a plan from an explicit state snapshot and compatibility authority."""

    current_version = current.version if current is not None else None
    target_version = manifest.version
    if current_version is None:
        return UpdatePlan(
            current_version=None,
            target_version=target_version,
            direction="install",
            allowed=True,
            migration_ids=(),
            rollback_migration_ids=(),
            blocked_effects=(),
            rollback_available=False,
            reason="fresh_install",
        )
    transition = matrix.transition(current_version, target_version)
    direction = _plan_direction(
        current_version,
        target_version,
        has_pending_migrations=bool(transition and transition.migration_ids),
    )
    if transition is None:
        return UpdatePlan(
            current_version=current_version,
            target_version=target_version,
            direction=direction,
            allowed=False,
            migration_ids=(),
            rollback_migration_ids=(),
            blocked_effects=(),
            rollback_available=current.previous_slot is not None,
            reason="unsupported_transition",
        )
    if not transition.supported:
        return UpdatePlan(
            current_version=current_version,
            target_version=target_version,
            direction=direction,
            allowed=False,
            migration_ids=(),
            rollback_migration_ids=(),
            blocked_effects=(),
            rollback_available=current.previous_slot is not None,
            reason="incompatible_transition",
            notes=transition.notes,
        )
    active_effects = {item.strip() for item in in_flight_effects if item.strip()}
    applied_migrations = set(current.applied_migrations)
    pending_migrations = tuple(
        migration_id
        for migration_id in transition.migration_ids
        if migration_id not in applied_migrations
    )
    pending_migration_set = set(pending_migrations)
    pending_rollback_migrations = tuple(
        rollback_id
        for migration_id, rollback_id in reversed(
            tuple(zip(transition.migration_ids, transition.rollback_migration_ids))
        )
        if migration_id in pending_migration_set
    )
    if pending_migrations and not pending_rollback_migrations:
        return UpdatePlan(
            current_version=current_version,
            target_version=target_version,
            direction=direction,
            allowed=False,
            migration_ids=pending_migrations,
            rollback_migration_ids=(),
            blocked_effects=(),
            rollback_available=current.previous_slot is not None,
            reason="migration_rollback_undefined",
            notes=transition.notes,
        )
    blocked_effects = tuple(
        effect for effect in transition.blocked_effects if effect in active_effects
    )
    if blocked_effects:
        return UpdatePlan(
            current_version=current_version,
            target_version=target_version,
            direction=direction,
            allowed=False,
            migration_ids=pending_migrations,
            rollback_migration_ids=pending_rollback_migrations,
            blocked_effects=blocked_effects,
            rollback_available=current.previous_slot is not None,
            reason="blocked_in_flight_effects",
            notes=transition.notes,
        )
    if current_version == target_version and not pending_migrations:
        direction = "noop"
    elif current_version == target_version:
        direction = "migrate"
    return UpdatePlan(
        current_version=current_version,
        target_version=target_version,
        direction=direction,
        allowed=True,
        migration_ids=pending_migrations,
        rollback_migration_ids=pending_rollback_migrations,
        blocked_effects=(),
        rollback_available=current.previous_slot is not None,
        reason="compatible",
        notes=transition.notes,
    )


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
        applied_migrations = _require_string_list(
            value.get("applied_migrations"),
            "active.applied_migrations",
            pattern=_MIGRATION_ID,
        )
        previous_applied_migrations = _require_string_list(
            value.get("previous_applied_migrations"),
            "active.previous_applied_migrations",
            pattern=_MIGRATION_ID,
        )
        rollback_migration_ids = _require_string_list(
            value.get("rollback_migration_ids"),
            "active.rollback_migration_ids",
            pattern=_MIGRATION_ID,
        )
        previous_rollback_migration_ids = _require_string_list(
            value.get("previous_rollback_migration_ids"),
            "active.previous_rollback_migration_ids",
            pattern=_MIGRATION_ID,
        )
        migration_delta = set(applied_migrations) ^ set(previous_applied_migrations)
        has_rollback_ids = "rollback_migration_ids" in value
        has_previous_rollback_ids = "previous_rollback_migration_ids" in value
        if has_rollback_ids != has_previous_rollback_ids:
            raise UpdateError(
                "active migration rollback metadata must contain both directions"
            )
        if has_rollback_ids and (
            len(rollback_migration_ids) != len(migration_delta)
            or len(previous_rollback_migration_ids) != len(migration_delta)
        ):
            raise UpdateError(
                "active migration rollback ids must map one-to-one to the ledger delta"
            )
        return ActivationRecord(
            active_slot,
            version,
            previous_slot,
            previous_version,
            applied_migrations,
            previous_applied_migrations,
            rollback_migration_ids,
            previous_rollback_migration_ids,
        )

    def plan(
        self,
        manifest: UpdateManifest,
        matrix: CompatibilityMatrix,
        *,
        in_flight_effects: Iterable[str] = (),
    ) -> UpdatePlan:
        """Validate one transition before activation, fail-closed."""

        if self.state_path.exists():
            raise UpdateError("cannot validate a plan while another update is in flight")
        return _build_update_plan(
            self.current(),
            manifest,
            matrix,
            in_flight_effects=in_flight_effects,
        )

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
        plan: UpdatePlan | None = None,
        matrix: CompatibilityMatrix | None = None,
        in_flight_effects: Iterable[str] = (),
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
        if old is not None and (plan is None or matrix is None):
            raise UpdateError(
                "existing installations require a compatibility plan and matrix"
            )
        if plan is not None:
            if matrix is None:
                raise UpdateError("an update plan requires its compatibility matrix")
            expected_plan = _build_update_plan(
                old,
                staged.manifest,
                matrix,
                in_flight_effects=in_flight_effects,
            )
            if plan != expected_plan:
                raise UpdateError(
                    "update plan does not match the compatibility matrix"
                )
            if not plan.allowed:
                raise UpdateError(f"update plan is blocked: {plan.reason}")
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
        applied_migrations = _merge_migrations(
            old.applied_migrations if old is not None else (),
            plan.migration_ids if plan is not None else (),
        )
        record = ActivationRecord(
            staged.slot,
            staged.manifest.version,
            old.active_slot if old else None,
            old.version if old else None,
            applied_migrations,
            old.applied_migrations if old else (),
            plan.rollback_migration_ids if plan is not None else (),
            plan.migration_ids if plan is not None else (),
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
        if (
            current.applied_migrations != current.previous_applied_migrations
            and not current.rollback_migration_ids
        ):
            raise UpdateError(
                "migration rollback contract is missing; refusing binary-only rollback"
            )
        previous_path = self.slots / current.previous_slot
        if not previous_path.is_dir():
            raise UpdateError("previous slot is missing; refusing destructive rollback")
        record = ActivationRecord(
            current.previous_slot,
            current.previous_version or self._slot_version(previous_path),
            current.active_slot,
            current.version,
            current.previous_applied_migrations,
            current.applied_migrations,
            current.previous_rollback_migration_ids,
            current.rollback_migration_ids,
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
                self._finish_commit(current)
                return current
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
                "applied_migrations": list(record.applied_migrations),
                "previous_applied_migrations": list(record.previous_applied_migrations),
                "rollback_migration_ids": list(record.rollback_migration_ids),
                "previous_rollback_migration_ids": list(
                    record.previous_rollback_migration_ids
                ),
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


def _merge_migrations(
    existing: Iterable[str], new_items: Iterable[str]
) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(existing) + list(new_items):
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return tuple(merged)


def _plan_direction(
    current_version: str,
    target_version: str,
    *,
    has_pending_migrations: bool,
) -> str:
    if current_version == target_version:
        return "migrate" if has_pending_migrations else "noop"
    current_parts = tuple(int(piece) for piece in current_version.split("."))
    target_parts = tuple(int(piece) for piece in target_version.split("."))
    return "upgrade" if target_parts > current_parts else "downgrade"


__all__ = [
    "ActivationRecord",
    "CompatibilityMatrix",
    "CompatibilityRule",
    "COMPATIBILITY_SCHEMA",
    "COMPATIBILITY_VERSION",
    "ManifestError",
    "MAX_ARTIFACT_BYTES",
    "MAX_FILES",
    "MAX_UNPACKED_BYTES",
    "StagedUpdate",
    "UpdateContract",
    "UpdateError",
    "UpdateInterrupted",
    "UpdateManifest",
    "UpdatePlan",
    "directory_sha256",
]
