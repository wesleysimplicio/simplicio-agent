"""One-shot state migrator: ``~/.hermes`` -> ``~/.simplicio/agent`` (issue #117).

Scope note (read this before wiring this module into a hot path): issue
#117's full plan flips the *default* HOME returned by
``hermes_constants.get_hermes_home()`` to ``~/.simplicio/agent`` and drives
the migration transactionally from inside that accessor (locking, staging,
per-subsystem merge rules, ``simplicio-agent doctor`` reporting, a 2-release
dual-read window, etc). ``get_hermes_home()`` is imported at module-import
time by 30+ call sites across this codebase, so flipping its default is a
repo-wide behavioural change that needs its own carefully reviewed PR (and
the clean-machine gate in #195) — it is deliberately **not** done here.

What this module *does* provide, real and tested: the migration primitive
itself — ``migrate_state()`` — a **copy-then-mark, idempotent, non-destructive**
one-shot mover from a legacy root to a new root, plus ``migrate_default_state()``
which wires it to the concrete legacy (``get_hermes_home()``) and canonical
new (``~/.simplicio/agent`` / ``%LOCALAPPDATA%\\simplicio\\agent``) roots for
this rename. Nothing calls ``migrate_default_state()`` automatically yet;
that wiring (into CLI startup, behind the ``--no-migrate`` opt-out) is the
next PR once this primitive has landed and been reviewed.

Design constraints (per the AC in issue #117):

- **Never destructive.** Only ``copy2``/``copytree``, never ``move``/``rmtree``
  on the *source*. The legacy root is left untouched no matter what.
- **Idempotent.** A completed migration writes a marker file inside the new
  root; a second call is a fast no-op. An *interrupted* migration (process
  killed mid-copy) leaves no marker, so a retry resumes: already-copied
  files are skipped, directories are re-merged with ``dirs_exist_ok=True``.
- **``--no-migrate`` opt-out.** ``no_migrate=True`` (or the
  ``SIMPLICIO_AGENT_NO_MIGRATE``/``HERMES_NO_MIGRATE`` env alias via
  :func:`agent.env_alias.env_get_bool`) skips migration entirely and reports
  why, without touching the filesystem.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent.env_alias import env_get_bool

MARKER_NAME = ".simplicio_migrated_from_hermes"


@dataclass(frozen=True)
class MigrationReport:
    """Outcome of one :func:`migrate_state` call. Never contains secret values."""

    source: Path
    dest: Path
    migrated: bool = False
    already_migrated: bool = False
    dry_run: bool = False
    skipped_reason: str | None = None
    copied_entries: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when nothing needs attention: migrated, already migrated, or
        legitimately skipped (opt-out / nothing to migrate) with no errors."""
        return not self.errors


def _resolved_eq(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def _has_content(path: Path) -> bool:
    """Mirrors ``hermes_constants._legacy_path_has_content`` for a root dir:
    a directory with at least one entry counts; missing or empty does not."""
    try:
        if not path.is_dir():
            return path.exists()
        next(path.iterdir())
        return True
    except StopIteration:
        return False
    except OSError:
        # Unreadable — assume occupied rather than silently skipping real data.
        return True


def migrate_state(
    legacy_home: Path,
    new_home: Path,
    *,
    dry_run: bool = False,
    no_migrate: bool = False,
) -> MigrationReport:
    """Copy ``legacy_home`` into ``new_home`` once, non-destructively.

    Args:
        legacy_home: the old state root (e.g. ``~/.hermes``).
        new_home: the new canonical state root (e.g. ``~/.simplicio/agent``).
        dry_run: report what *would* be copied without writing anything.
        no_migrate: opt-out — skip migration entirely, report why.

    Returns:
        A :class:`MigrationReport` describing what happened. Idempotent: a
        second call after a successful migration returns
        ``already_migrated=True`` and touches nothing.
    """
    legacy_home = Path(legacy_home)
    new_home = Path(new_home)

    if no_migrate:
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            skipped_reason="migration disabled via --no-migrate / "
            "SIMPLICIO_AGENT_NO_MIGRATE",
        )

    marker = new_home / MARKER_NAME
    if marker.exists():
        return MigrationReport(source=legacy_home, dest=new_home, already_migrated=True)

    if _resolved_eq(legacy_home, new_home):
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            skipped_reason="source and destination resolve to the same path",
        )

    if not _has_content(legacy_home):
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            skipped_reason="no legacy state found at source (fresh install)",
        )

    try:
        entries = sorted(legacy_home.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            errors=[f"cannot list source: {exc}"],
        )

    if dry_run:
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            dry_run=True,
            copied_entries=[e.name for e in entries if e.name != MARKER_NAME],
        )

    try:
        new_home.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            errors=[f"cannot create destination: {exc}"],
        )

    copied: list[str] = []
    errors: list[str] = []
    for entry in entries:
        if entry.name == MARKER_NAME:
            continue
        dest = new_home / entry.name
        try:
            if entry.is_dir() and not entry.is_symlink():
                # dirs_exist_ok=True makes a resumed/interrupted migration
                # continue instead of failing on an already-partially-copied
                # directory from a prior, killed run.
                shutil.copytree(entry, dest, dirs_exist_ok=True)
            elif dest.exists():
                # Already copied by a previous (interrupted) run — idempotent
                # continuation, don't re-copy or error.
                pass
            else:
                shutil.copy2(entry, dest, follow_symlinks=False)
            copied.append(entry.name)
        except OSError as exc:
            errors.append(f"{entry.name}: {exc}")

    if errors:
        # Do NOT write the marker: a retry must re-attempt the failed entries.
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            copied_entries=copied,
            errors=errors,
        )

    try:
        marker.write_text(
            json.dumps(
                {
                    "schema": "simplicio.state-migration/v1",
                    "migrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source": str(legacy_home),
                    "entries": copied,
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        # Migration succeeded but we couldn't record it — report as an error
        # so the caller knows a retry may re-copy (harmless: copytree/copy2
        # above are already idempotent), rather than silently claiming success.
        return MigrationReport(
            source=legacy_home,
            dest=new_home,
            copied_entries=copied,
            errors=[f"migration succeeded but marker write failed: {exc}"],
        )

    return MigrationReport(source=legacy_home, dest=new_home, migrated=True, copied_entries=copied)


def canonical_new_home() -> Path:
    """Return the platform-native ``~/.simplicio/agent`` target for this rename.

    Mirrors ``hermes_constants._get_platform_default_hermes_home()``'s
    platform split, but is a pure function with no fallback/env-var reading
    of its own — this is *only* the migration target, not a HOME resolver.
    """
    if sys.platform == "win32":
        import os as _os

        local_appdata = _os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / "simplicio" / "agent"
    return Path.home() / ".simplicio" / "agent"


def migrate_default_state(*, dry_run: bool = False) -> MigrationReport:
    """Migrate the real, current legacy HOME (``get_hermes_home()``) into the
    canonical new root (:func:`canonical_new_home`).

    Not called automatically anywhere yet — see the module docstring. This
    is the entry point a future opt-in CLI wiring (or a test) calls.
    """
    from hermes_constants import get_hermes_home

    no_migrate = env_get_bool("NO_MIGRATE", False)
    return migrate_state(
        get_hermes_home(),
        canonical_new_home(),
        dry_run=dry_run,
        no_migrate=no_migrate,
    )
