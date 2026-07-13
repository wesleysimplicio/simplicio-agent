"""Bounded, non-destructive state migration primitives for issue #117.

This module deliberately stops short of flipping the default returned by
``hermes_constants.get_hermes_home()`` or wiring migration into every CLI
startup.  Those are repo-wide behavioural changes because the accessor is
imported by dozens of modules.  The slice here is the safer transaction
primitive: copy into a deterministic staging workspace, record progress in a
manifest and journal, preflight destination conflicts, then merge without
overwriting user data and write a completion marker.

The complete issue plan also calls for a generated registry of roughly 525
``HERMES_*`` variables and many named aliases.  That registry is intentionally
not invented here; ``agent.env_alias`` supplies the reusable precedence
primitive and the gap remains documented for a follow-up.
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.env_alias import env_get, env_get_bool

MIGRATION_SCHEMA = "simplicio.state-migration/v2"
MARKER_NAME = ".simplicio_migrated_from_hermes"
STAGING_DIR_NAME = ".simplicio-state-migration"
MANIFEST_NAME = "manifest.json"
JOURNAL_NAME = "journal.jsonl"
_METADATA_NAMES = frozenset({MARKER_NAME, STAGING_DIR_NAME})


@dataclass(frozen=True)
class MigrationReport:
    """Outcome of one migration attempt; paths contain no secret values."""

    source: Path
    dest: Path
    migrated: bool = False
    already_migrated: bool = False
    dry_run: bool = False
    skipped_reason: str | None = None
    copied_entries: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    manifest_path: Path | None = None
    journal_path: Path | None = None
    staging_path: Path | None = None

    @property
    def ok(self) -> bool:
        """True when the migration needs no operator attention."""
        return not self.errors and not self.conflicts


class _MergeConflict(Exception):
    """Raised if a destination changes between preflight and commit."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolved_eq(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _has_content(path: Path) -> bool:
    """Treat an unreadable source as occupied rather than silently skipping."""
    try:
        if not path.is_dir():
            return path.exists()
        next(path.iterdir())
        return True
    except StopIteration:
        return False
    except OSError:
        return True


def _workspace_for(new_home: Path) -> Path:
    name = new_home.name or "home"
    return new_home.parent / f".{name}{STAGING_DIR_NAME}"


def _metadata_paths(new_home: Path) -> tuple[Path, Path, Path, Path]:
    workspace = _workspace_for(new_home)
    return (
        workspace,
        workspace / "payload",
        workspace / MANIFEST_NAME,
        workspace / JOURNAL_NAME,
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON through a sibling temporary file and atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _append_journal(path: Path, event: str, **fields: Any) -> None:
    record = {"at": _utc_now(), "event": event, **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _same_entry(source: Path, destination: Path) -> bool:
    if source.is_symlink() or destination.is_symlink():
        try:
            return (
                source.is_symlink()
                and destination.is_symlink()
                and os.readlink(source) == os.readlink(destination)
            )
        except OSError:
            return False
    if source.is_dir() or destination.is_dir():
        return source.is_dir() and destination.is_dir()
    try:
        return filecmp.cmp(source, destination, shallow=False)
    except OSError:
        return False


def _copy_to_stage(source: Path, staged: Path) -> None:
    """Recursively fill staging; reruns safely complete partial directories."""
    if source.is_symlink():
        if _lexists(staged) and _same_entry(source, staged):
            return
        if _lexists(staged):
            raise OSError(f"staging path conflicts with source symlink: {staged}")
        staged.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.readlink(source), staged, target_is_directory=source.is_dir())
        return
    if source.is_dir():
        staged.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _copy_to_stage(child, staged / child.name)
        return
    if _lexists(staged) and _same_entry(source, staged):
        return
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, staged, follow_symlinks=False)


def _conflicts(source: Path, destination: Path, relative: str) -> list[str]:
    if not _lexists(destination):
        return []
    if _same_entry(source, destination) and not source.is_dir():
        return []
    if source.is_dir() and not source.is_symlink():
        if not destination.is_dir() or destination.is_symlink():
            return [relative]
        found: list[str] = []
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            child_relative = f"{relative}/{child.name}" if relative else child.name
            found.extend(_conflicts(child, destination / child.name, child_relative))
        return found
    return [] if _same_entry(source, destination) else [relative]


def _merge_entry(source: Path, destination: Path, relative: str) -> None:
    conflicts = _conflicts(source, destination, relative)
    if conflicts:
        raise _MergeConflict(", ".join(conflicts))
    if _lexists(destination):
        if source.is_dir() and not source.is_symlink():
            for child in sorted(source.iterdir(), key=lambda item: item.name):
                _merge_entry(
                    child, destination / child.name, f"{relative}/{child.name}"
                )
        return
    if source.is_symlink():
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(
            os.readlink(source), destination, target_is_directory=source.is_dir()
        )
    elif source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _merge_entry(child, destination / child.name, f"{relative}/{child.name}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)


def _manifest_payload(
    source: Path,
    destination: Path,
    staging: Path,
    entries: list[Path],
    *,
    status: str,
    entry_status: dict[str, str] | None = None,
) -> dict[str, Any]:
    states = entry_status or {}
    return {
        "schema": MIGRATION_SCHEMA,
        "source": str(source),
        "destination": str(destination),
        "staging": str(staging),
        "status": status,
        "updated_at": _utc_now(),
        "entries": [
            {"name": entry.name, "status": states.get(entry.name, "planned")}
            for entry in entries
        ],
    }


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("schema") != MIGRATION_SCHEMA:
        raise ValueError(f"unsupported migration manifest: {path}")
    return payload


def migrate_state(
    legacy_home: Path,
    new_home: Path,
    *,
    dry_run: bool = False,
    no_migrate: bool = False,
) -> MigrationReport:
    """Copy legacy state to a new root with resumable transactional progress.

    The source is never removed.  A run first fills a sibling staging
    workspace, then preflights every destination path.  Existing destination
    content is accepted only when byte/link-identical; conflicting content
    blocks the commit and leaves both source and destination untouched.
    """
    legacy_home = Path(legacy_home)
    new_home = Path(new_home)
    workspace, staged_root, manifest_path, journal_path = _metadata_paths(new_home)
    base_report = {
        "source": legacy_home,
        "dest": new_home,
        "manifest_path": manifest_path,
        "journal_path": journal_path,
        "staging_path": staged_root,
    }

    if no_migrate:
        return MigrationReport(
            **base_report,
            skipped_reason="migration disabled via --no-migrate / environment",
        )

    marker = new_home / MARKER_NAME
    if marker.exists():
        return MigrationReport(**base_report, already_migrated=True)

    if _resolved_eq(legacy_home, new_home):
        return MigrationReport(
            **base_report,
            skipped_reason="source and destination resolve to the same path",
        )
    if not _has_content(legacy_home):
        return MigrationReport(
            **base_report,
            skipped_reason="no legacy state found at source (fresh install)",
        )

    try:
        entries = [
            entry
            for entry in sorted(legacy_home.iterdir(), key=lambda item: item.name)
            if entry.name not in _METADATA_NAMES
        ]
    except OSError as exc:
        return MigrationReport(**base_report, errors=[f"cannot list source: {exc}"])

    names = [entry.name for entry in entries]
    if dry_run:
        return MigrationReport(**base_report, dry_run=True, copied_entries=names)

    try:
        existing_manifest = _load_manifest(manifest_path)
        if existing_manifest is not None and (
            existing_manifest.get("source") != str(legacy_home)
            or existing_manifest.get("destination") != str(new_home)
        ):
            return MigrationReport(
                **base_report,
                conflicts=[
                    "migration workspace belongs to another source or destination"
                ],
            )
        workspace.mkdir(parents=True, exist_ok=True)
        staged_root.mkdir(parents=True, exist_ok=True)
        entry_status = {
            item["name"]: item.get("status", "planned")
            for item in (existing_manifest or {}).get("entries", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        _atomic_json(
            manifest_path,
            _manifest_payload(
                legacy_home,
                new_home,
                staged_root,
                entries,
                status="staging",
                entry_status=entry_status,
            ),
        )
        _append_journal(journal_path, "migration_started", entries=names)
    except (OSError, ValueError, TypeError) as exc:
        return MigrationReport(
            **base_report, errors=[f"cannot initialize migration journal: {exc}"]
        )

    copied: list[str] = []
    errors: list[str] = []
    for entry in entries:
        try:
            _copy_to_stage(entry, staged_root / entry.name)
            copied.append(entry.name)
            entry_status[entry.name] = "staged"
            _atomic_json(
                manifest_path,
                _manifest_payload(
                    legacy_home,
                    new_home,
                    staged_root,
                    entries,
                    status="staging",
                    entry_status=entry_status,
                ),
            )
            _append_journal(journal_path, "entry_staged", entry=entry.name)
        except OSError as exc:
            entry_status[entry.name] = "partial"
            errors.append(f"{entry.name}: {exc}")
            try:
                _atomic_json(
                    manifest_path,
                    _manifest_payload(
                        legacy_home,
                        new_home,
                        staged_root,
                        entries,
                        status="staging_failed",
                        entry_status=entry_status,
                    ),
                )
                _append_journal(
                    journal_path, "entry_failed", entry=entry.name, error=str(exc)
                )
            except OSError as journal_exc:
                errors.append(f"journal update failed: {journal_exc}")

    if errors:
        return MigrationReport(**base_report, copied_entries=copied, errors=errors)

    staged_entries = [staged_root / entry.name for entry in entries]
    conflicts: list[str] = []
    for entry, staged in zip(entries, staged_entries):
        conflicts.extend(_conflicts(staged, new_home / entry.name, entry.name))
    if conflicts:
        try:
            _atomic_json(
                manifest_path,
                _manifest_payload(
                    legacy_home,
                    new_home,
                    staged_root,
                    entries,
                    status="conflict",
                    entry_status=entry_status,
                ),
            )
            _append_journal(journal_path, "conflict", paths=conflicts)
        except OSError as exc:
            errors.append(f"journal update failed: {exc}")
        return MigrationReport(
            **base_report,
            copied_entries=copied,
            conflicts=sorted(set(conflicts)),
            errors=errors,
        )

    for entry, staged in zip(entries, staged_entries):
        try:
            _merge_entry(staged, new_home / entry.name, entry.name)
            entry_status[entry.name] = "committed"
            _atomic_json(
                manifest_path,
                _manifest_payload(
                    legacy_home,
                    new_home,
                    staged_root,
                    entries,
                    status="committing",
                    entry_status=entry_status,
                ),
            )
            _append_journal(journal_path, "entry_committed", entry=entry.name)
        except (_MergeConflict, OSError) as exc:
            errors.append(f"{entry.name}: {exc}")
            break

    if errors:
        return MigrationReport(**base_report, copied_entries=copied, errors=errors)

    try:
        _atomic_json(
            manifest_path,
            _manifest_payload(
                legacy_home,
                new_home,
                staged_root,
                entries,
                status="complete",
                entry_status=entry_status,
            ),
        )
        _append_journal(journal_path, "migration_complete", entries=names)
        _atomic_json(
            marker,
            {
                "schema": MIGRATION_SCHEMA,
                "migrated_at": _utc_now(),
                "source": str(legacy_home),
                "entries": names,
                "manifest": str(manifest_path),
                "journal": str(journal_path),
            },
        )
    except OSError as exc:
        return MigrationReport(
            **base_report,
            copied_entries=copied,
            errors=[f"completion record failed: {exc}"],
        )

    return MigrationReport(**base_report, migrated=True, copied_entries=copied)


def canonical_new_home() -> Path:
    """Return the platform-native target for the future default-home rename."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = (
            Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        )
        return base / "simplicio" / "agent"
    return Path.home() / ".simplicio" / "agent"


def migrate_default_state(*, dry_run: bool = False) -> MigrationReport:
    """Migrate the legacy default/custom root to the canonical target.

    ``HERMES_HOME`` is the explicit legacy source when present.  The
    canonical ``SIMPLICIO_AGENT_HOME`` destination wins when present; the
    normal target otherwise comes from :func:`canonical_new_home`.
    """
    legacy_value = os.environ.get("HERMES_HOME", "").strip()
    legacy_home = Path(legacy_value) if legacy_value else _legacy_platform_home()
    canonical_value = (
        env_get("HOME") if os.environ.get("SIMPLICIO_AGENT_HOME", "").strip() else None
    )
    destination = Path(canonical_value) if canonical_value else canonical_new_home()
    return migrate_state(
        legacy_home,
        destination,
        dry_run=dry_run,
        no_migrate=env_get_bool("NO_MIGRATE", False),
    )


def _legacy_platform_home() -> Path:
    """Return the pre-rename platform default without consulting HOME aliases."""
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = (
            Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        )
        return base / "hermes"
    return Path.home() / ".hermes"
