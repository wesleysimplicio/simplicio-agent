"""Small, fail-closed preflight boundary for local updates.

This module deliberately owns only three concerns needed before an update can
start: identifying the installation, serialising update attempts, and taking
a metadata-bearing pre-update snapshot.  File hashing, blob storage, restore,
and snapshot receipts remain in :mod:`tools.transaction_primitives`.

It does not fetch releases, mutate a checkout, or claim that an update is
live.  Those operations belong to the later updater/supervisor slices.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from hermes_cli.config import detect_install_method
from tools.transaction_primitives import (
    SnapshotManifest,
    SnapshotReceipt,
    SnapshotStore,
)


INSTALLATION_SCHEMA = "simplicio.installation/v1"
LOCK_SCHEMA = "simplicio.update-lock/v1"
PRE_UPDATE_SCHEMA = "simplicio.pre-update/v1"


class UpdatePreflightError(RuntimeError):
    """The update cannot safely enter its mutation phase."""


class UpdateLockError(UpdatePreflightError):
    """An update lock is already held or cannot be released safely."""


class PreUpdateMetadataError(UpdatePreflightError):
    """Pre-update metadata is malformed or unavailable."""


@dataclass(frozen=True)
class InstallationInfo:
    """Deterministic description of the code installation being updated."""

    state: str
    install_type: str
    root: Path
    version: str | None = None
    commit: str | None = None

    def __post_init__(self) -> None:
        if self.state not in {"new", "existing"}:
            raise ValueError("installation state must be new or existing")
        for name in ("install_type", "version", "commit"):
            value = getattr(self, name)
            if value is not None and (not str(value).strip() or "\n" in str(value)):
                raise ValueError(f"installation {name} must be a single line")

    @property
    def is_new(self) -> bool:
        return self.state == "new"

    @property
    def is_existing(self) -> bool:
        return self.state == "existing"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": INSTALLATION_SCHEMA,
            "state": self.state,
            "install_type": self.install_type,
            "root": self.root.as_posix(),
            "version": self.version,
            "commit": self.commit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "InstallationInfo":
        if value.get("schema") != INSTALLATION_SCHEMA:
            raise PreUpdateMetadataError("unsupported installation metadata schema")
        try:
            root = Path(str(value["root"])).expanduser().resolve()
            return cls(
                state=str(value["state"]),
                install_type=str(value["install_type"]),
                root=root,
                version=_optional_text(value.get("version")),
                commit=_optional_text(value.get("commit")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PreUpdateMetadataError("installation metadata is malformed") from exc


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise ValueError("metadata text must be non-empty when present")
    return text


def _read_version(root: Path) -> str | None:
    version_file = root / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    if version:
        return version
    try:
        with (root / "pyproject.toml").open("rb") as handle:
            value = tomllib.load(handle)
        project = value.get("project", {})
        return (
            _optional_text(project.get("version"))
            if isinstance(project, dict)
            else None
        )
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return None


def _read_commit(root: Path) -> str | None:
    git = root / ".git"
    if not git.is_dir():
        return None
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[5:].strip()
            return (git / ref).read_text(encoding="utf-8").strip() or None
        return head or None
    except OSError:
        return None


def detect_installation(project_root: Path) -> InstallationInfo:
    """Detect a new or existing installation without changing the filesystem.

    A code-scoped ``.install_method`` is authoritative through the existing
    detector.  A checkout, package tree, or version marker is existing; an
    absent/empty root is new.  The detector intentionally does not infer a
    release from the process environment or contact a package manager.
    """

    root = Path(project_root).expanduser().resolve()
    markers = (
        root / ".install_method",
        root / ".git",
        root / "pyproject.toml",
        root / "VERSION",
    )
    existing = root.is_dir() and any(marker.exists() for marker in markers)
    if not existing:
        return InstallationInfo("new", "unknown", root)
    try:
        install_type = detect_install_method(root).strip().lower() or "unknown"
    except Exception:
        install_type = "unknown"
    # Git worktrees represent ``.git`` as a file, while the existing helper
    # intentionally checks only the directory form for its legacy callers.
    if install_type == "pip" and (root / ".git").exists():
        install_type = "git"
    return InstallationInfo(
        "existing",
        install_type,
        root,
        version=_read_version(root),
        commit=_read_commit(root),
    )


class UpdateLock:
    """Cross-platform, atomic, fail-closed exclusive update lock.

    The lock uses ``O_EXCL`` instead of advisory locks so a second updater
    cannot enter even when it uses a different Python process.  Stale locks
    are never reclaimed automatically; recovery must be an explicit operator
    decision, because guessing that an owner died can overlap a live update.
    """

    def __init__(
        self, path: Path, *, owner: str | None = None, token: str | None = None
    ):
        self.path = Path(path).expanduser()
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}"
        self.token = token or uuid.uuid4().hex
        self._held = False

    def acquire(self) -> "UpdateLock":
        if self._held:
            raise UpdateLockError("update lock is already held by this owner")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": LOCK_SCHEMA,
            "owner": self.owner,
            "pid": os.getpid(),
            "token": self.token,
        }
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise UpdateLockError("update lock is already held") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self.path.unlink(missing_ok=True)
            raise
        self._held = True
        return self

    def release(self) -> None:
        if not self._held:
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UpdateLockError("update lock cannot be verified for release") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema") != LOCK_SCHEMA
            or value.get("token") != self.token
        ):
            raise UpdateLockError("update lock owner mismatch")
        self.path.unlink()
        self._held = False

    def __enter__(self) -> "UpdateLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.release()


def acquire_update_lock(
    path: Path, *, owner: str | None = None, token: str | None = None
) -> UpdateLock:
    """Acquire and return an exclusive update lock for use as a context manager."""

    return UpdateLock(path, owner=owner, token=token).acquire()


@dataclass(frozen=True)
class PreUpdateSnapshot:
    """A transaction-primitives snapshot plus its update-facing metadata."""

    manifest: SnapshotManifest
    installation: InstallationInfo
    receipt: SnapshotReceipt

    @property
    def snapshot_id(self) -> str:
        return self.manifest.snapshot_id

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PRE_UPDATE_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "installation": self.installation.to_dict(),
            "manifest": self.manifest.to_dict(),
            "receipt": self.receipt.to_dict(),
        }


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class PreUpdateSnapshotStore:
    """Persist pre-update metadata beside a shared transaction snapshot store."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.snapshots = SnapshotStore(self.root / "content")
        self.metadata = self.root / "metadata"

    def create(
        self,
        source: Path,
        installation: InstallationInfo,
        *,
        commit: str | None = None,
        timestamp: str | None = None,
        signature: str | None = None,
    ) -> PreUpdateSnapshot:
        commit = commit if commit is not None else installation.commit
        manifest = self.snapshots.create(
            Path(source), commit=commit, timestamp=timestamp, signature=signature
        )
        receipt = SnapshotReceipt(
            operation="pre-update-snapshot",
            before_digest=None,
            after_digest=manifest.snapshot_id,
            verified=True,
        )
        snapshot = PreUpdateSnapshot(manifest, installation, receipt)
        _atomic_json(self.metadata / f"{manifest.snapshot_id}.json", snapshot.to_dict())
        return snapshot

    def load(self, snapshot_id: str) -> PreUpdateSnapshot:
        manifest = self.snapshots.load(snapshot_id)
        try:
            value = json.loads(
                (self.metadata / f"{snapshot_id}.json").read_text(encoding="utf-8")
            )
            if not isinstance(value, dict) or value.get("schema") != PRE_UPDATE_SCHEMA:
                raise ValueError
            if value.get("snapshot_id") != snapshot_id:
                raise ValueError
            installation_value = value.get("installation")
            if not isinstance(installation_value, dict):
                raise ValueError
            installation = InstallationInfo.from_dict(installation_value)
        except (OSError, TypeError, ValueError, PreUpdateMetadataError) as exc:
            raise PreUpdateMetadataError("pre-update metadata is unavailable") from exc
        receipt = SnapshotReceipt(
            operation="pre-update-snapshot",
            before_digest=None,
            after_digest=manifest.snapshot_id,
            verified=True,
        )
        return PreUpdateSnapshot(manifest, installation, receipt)

    def restore(
        self,
        snapshot: PreUpdateSnapshot | str,
        target: Path,
        *,
        verify_only: bool = False,
    ) -> SnapshotReceipt:
        """Delegate restore and verification to the shared primitives."""

        manifest = (
            self.load(snapshot).manifest
            if isinstance(snapshot, str)
            else snapshot.manifest
        )
        return self.snapshots.restore(manifest, Path(target), verify_only=verify_only)

    def create_locked(
        self,
        source: Path,
        installation: InstallationInfo,
        lock_path: Path,
        **metadata: str | None,
    ) -> PreUpdateSnapshot:
        """Capture a snapshot while holding one exclusive update lock."""

        with UpdateLock(lock_path):
            return self.create(source, installation, **metadata)


__all__ = [
    "INSTALLATION_SCHEMA",
    "LOCK_SCHEMA",
    "PRE_UPDATE_SCHEMA",
    "InstallationInfo",
    "PreUpdateMetadataError",
    "PreUpdateSnapshot",
    "PreUpdateSnapshotStore",
    "UpdateLock",
    "UpdateLockError",
    "UpdatePreflightError",
    "acquire_update_lock",
    "detect_installation",
]
