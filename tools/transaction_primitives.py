"""Small deterministic primitives for checkpointed, transactional updates.

This module deliberately owns only immutable snapshots, their journal, and the
atomic update pointer.  It does not start processes, fetch releases, or touch a
working tree outside an explicitly supplied directory.  The primitives are
useful as the local, testable boundary for issues #315 and #316 while the
runtime/supervisor integration is developed separately.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping


SNAPSHOT_SCHEMA = "simplicio.snapshot/v1"
JOURNAL_SCHEMA = "simplicio.journal/v1"
RECEIPT_SCHEMA = "simplicio.hbp-receipt/v1"


class TransactionError(RuntimeError):
    """A snapshot or update transaction cannot safely continue."""


class SnapshotError(TransactionError):
    """A snapshot is invalid, incomplete, or changed while being captured."""


class JournalError(TransactionError):
    """A journal is malformed or its hash chain is broken."""


def _validate_entry_path(path: str) -> None:
    posix = PurePosixPath(path.replace("\\", "/"))
    windows = PureWindowsPath(path)
    if (
        not path
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise SnapshotError("snapshot entry path must stay within its root")


def _validate_digest(digest: str) -> None:
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise SnapshotError("snapshot entry has an invalid digest")


def _validate_snapshot_id(snapshot_id: str) -> None:
    if (
        not isinstance(snapshot_id, str)
        or len(snapshot_id) != 64
        or any(char not in "0123456789abcdef" for char in snapshot_id)
    ):
        raise SnapshotError("invalid snapshot id")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise SnapshotError("snapshot metadata must be non-empty when present")
    return text


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    """Best-effort durability for a rename in a directory.

    Windows does not generally allow opening a directory as a file, while
    POSIX filesystems need the directory entry flushed separately from the
    renamed file.  The primitive remains usable on both platforms and makes
    the stronger durability step where the platform supports it.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _safe_files(root: Path) -> list[tuple[str, Path]]:
    root = root.expanduser()
    if root.is_symlink() or not root.is_dir():
        raise SnapshotError("snapshot root must be a real directory")
    root = root.resolve()
    result: list[tuple[str, Path]] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in directories + files:
            path = current_path / name
            if path.is_symlink():
                raise SnapshotError(f"snapshot contains symlink: {path}")
        for name in files:
            path = current_path / name
            try:
                if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                    raise SnapshotError(f"snapshot contains non-regular file: {path}")
            except FileNotFoundError as exc:
                raise SnapshotError(f"snapshot file disappeared: {path}") from exc
            relative = path.relative_to(root).as_posix()
            if not relative or relative.startswith("../") or "/../" in relative:
                raise SnapshotError("snapshot path escapes its root")
            result.append((relative, path))
    return result


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    digest: str
    size_bytes: int
    mode: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SnapshotEntry":
        try:
            if not isinstance(value["size_bytes"], int) or isinstance(
                value["size_bytes"], bool
            ):
                raise TypeError
            if not isinstance(value["mode"], int) or isinstance(value["mode"], bool):
                raise TypeError
            entry = cls(
                str(value["path"]),
                str(value["digest"]),
                value["size_bytes"],
                value["mode"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("snapshot entry is malformed") from exc
        _validate_entry_path(entry.path)
        _validate_digest(entry.digest)
        if entry.size_bytes < 0 or entry.mode < 0 or entry.mode > 0o7777:
            raise SnapshotError("snapshot entry has invalid size or mode")
        return entry


@dataclass(frozen=True)
class SnapshotManifest:
    snapshot_id: str
    entries: tuple[SnapshotEntry, ...]
    commit: str | None = None
    timestamp: str | None = None
    signature: str | None = None

    @property
    def root_digest(self) -> str:
        """The Merkle-style root for this manifest's sorted file entries."""
        return self.snapshot_id

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "root_digest": self.root_digest,
            "entries": [entry.to_dict() for entry in self.entries],
            "commit": self.commit,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SnapshotManifest":
        if value.get("schema") != SNAPSHOT_SCHEMA:
            raise SnapshotError("unsupported snapshot schema")
        raw_entries = value.get("entries", [])
        if not isinstance(raw_entries, list):
            raise SnapshotError("snapshot entries must be a list")
        try:
            entries = tuple(
                SnapshotEntry.from_dict(item)
                for item in raw_entries
                if isinstance(item, Mapping)
            )
        except SnapshotError:
            raise
        if len(entries) != len(raw_entries):
            raise SnapshotError("snapshot entry is malformed")
        if len({entry.path for entry in entries}) != len(entries):
            raise SnapshotError("snapshot contains duplicate paths")
        snapshot_id = str(value.get("snapshot_id", ""))
        _validate_snapshot_id(snapshot_id)
        if value.get("root_digest", snapshot_id) != snapshot_id:
            raise SnapshotError("snapshot root digest mismatch")
        manifest = cls(
            snapshot_id,
            entries,
            _optional_text(value.get("commit")),
            _optional_text(value.get("timestamp")),
            _optional_text(value.get("signature")),
        )
        if snapshot_tree_from_entries(entries) != snapshot_id:
            raise SnapshotError("snapshot manifest digest mismatch")
        return manifest


@dataclass(frozen=True)
class Equivalence:
    equivalent: bool
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()


@dataclass(frozen=True)
class SnapshotReceipt:
    """Stable, content-addressed evidence for a snapshot operation."""

    operation: str
    before_digest: str | None
    after_digest: str | None
    verified: bool
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation or "\n" in self.operation:
            raise ValueError("receipt operation must be a single non-empty line")
        for field_name in ("added", "removed", "changed"):
            object.__setattr__(
                self, field_name, tuple(sorted(getattr(self, field_name)))
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "operation": self.operation,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "verified": self.verified,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
        }

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


@dataclass(frozen=True)
class GarbageCollectionResult:
    """Deterministic report from one bounded snapshot GC pass."""

    removed_snapshots: tuple[str, ...] = ()
    removed_blobs: tuple[str, ...] = ()
    retained_snapshots: tuple[str, ...] = ()


def _file_digest(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    info = path.stat()
    return digest.hexdigest(), info.st_size, stat.S_IMODE(info.st_mode)


def _snapshot_ids_in_value(value: object) -> set[str]:
    """Conservatively retain every valid snapshot ID named by journal data."""
    found: set[str] = set()
    if isinstance(value, str):
        try:
            _validate_snapshot_id(value)
        except SnapshotError:
            return found
        found.add(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            found.update(_snapshot_ids_in_value(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_snapshot_ids_in_value(item))
    return found


def snapshot_tree(root: Path) -> SnapshotManifest:
    """Build a location-independent, deterministic manifest of ``root``."""
    entries = tuple(
        SnapshotEntry(relative, *_file_digest(path))
        for relative, path in _safe_files(Path(root))
    )
    payload = [entry.to_dict() for entry in entries]
    snapshot_id = hashlib.sha256(_canonical(payload)).hexdigest()
    return SnapshotManifest(snapshot_id, entries)


def shadow_equivalence(
    expected: SnapshotManifest | Path, actual: SnapshotManifest | Path
) -> Equivalence:
    """Compare a shadow snapshot with a live tree or another snapshot."""
    expected_manifest = (
        snapshot_tree(expected) if isinstance(expected, Path) else expected
    )
    actual_manifest = snapshot_tree(actual) if isinstance(actual, Path) else actual
    left = {entry.path: entry for entry in expected_manifest.entries}
    right = {entry.path: entry for entry in actual_manifest.entries}
    added = tuple(sorted(set(right) - set(left)))
    removed = tuple(sorted(set(left) - set(right)))
    changed = tuple(
        sorted(path for path in set(left) & set(right) if left[path] != right[path])
    )
    return Equivalence(not (added or removed or changed), added, removed, changed)


class SnapshotStore:
    """Content-addressed snapshot blobs and manifests."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.blobs = self.root / "blobs"
        self.manifests = self.root / "snapshots"

    def _blob(self, entry: SnapshotEntry) -> Path:
        """Return a verified regular blob path, rejecting symlink escapes."""
        _validate_digest(entry.digest)
        blob = self.blobs / entry.digest
        try:
            mode = blob.stat(follow_symlinks=False).st_mode
        except FileNotFoundError:
            raise SnapshotError(f"missing or corrupt snapshot blob: {entry.path}")
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise SnapshotError(f"missing or corrupt snapshot blob: {entry.path}")
        return blob

    def create(
        self,
        source: Path,
        *,
        commit: str | None = None,
        timestamp: str | None = None,
        signature: str | None = None,
    ) -> SnapshotManifest:
        base_manifest = snapshot_tree(source)
        manifest = SnapshotManifest(
            base_manifest.snapshot_id,
            base_manifest.entries,
            _optional_text(commit),
            _optional_text(timestamp),
            _optional_text(signature),
        )
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        for entry in manifest.entries:
            blob = self.blobs / entry.digest
            if blob.is_symlink():
                blob.unlink()
            if blob.exists() and blob.is_file():
                if _file_digest(blob)[0] == entry.digest:
                    continue
                blob.unlink()
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{entry.digest}.", suffix=".tmp", dir=self.blobs
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                shutil.copyfile(Path(source).resolve() / entry.path, temporary)
                digest, size, _ = _file_digest(temporary)
                if digest != entry.digest or size != entry.size_bytes:
                    raise SnapshotError("source changed while snapshotting")
                with temporary.open("r+b") as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, blob)
                _fsync_directory(self.blobs)
            finally:
                temporary.unlink(missing_ok=True)
        if snapshot_tree(source).snapshot_id != manifest.snapshot_id:
            raise SnapshotError("source changed while snapshotting")
        _atomic_json(
            self.manifests / f"{manifest.snapshot_id}.json", manifest.to_dict()
        )
        _fsync_directory(self.manifests)
        return manifest

    def load(self, snapshot_id: str) -> SnapshotManifest:
        _validate_snapshot_id(snapshot_id)
        path = self.manifests / f"{snapshot_id}.json"
        if path.is_symlink():
            raise SnapshotError("snapshot manifest is unavailable")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            manifest = SnapshotManifest.from_dict(value)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("snapshot manifest is unavailable") from exc
        if manifest.snapshot_id != snapshot_id:
            raise SnapshotError("snapshot manifest digest mismatch")
        return manifest

    def verify(
        self, manifest: SnapshotManifest | str, target: Path
    ) -> "SnapshotReceipt":
        """Verify ``target`` against a snapshot without writing to either side."""
        if isinstance(manifest, str):
            manifest = self.load(manifest)
        _validate_manifest(manifest)
        actual = snapshot_tree(Path(target))
        comparison = shadow_equivalence(manifest, actual)
        return SnapshotReceipt(
            operation="verify",
            before_digest=manifest.root_digest,
            after_digest=actual.root_digest,
            verified=comparison.equivalent,
            added=comparison.added,
            removed=comparison.removed,
            changed=comparison.changed,
        )

    def restore(
        self,
        manifest: SnapshotManifest | str,
        target: Path,
        *,
        verify_only: bool = False,
    ) -> "SnapshotReceipt":
        """Materialize a verified snapshot, or only verify it when requested."""
        if isinstance(manifest, str):
            manifest = self.load(manifest)
        _validate_manifest(manifest)
        if verify_only:
            return self.verify(manifest, target)
        for entry in manifest.entries:
            _validate_entry_path(entry.path)
            _validate_digest(entry.digest)
            blob = self._blob(entry)
            digest, size, _ = _file_digest(blob)
            if digest != entry.digest or size != entry.size_bytes:
                raise SnapshotError(f"missing or corrupt snapshot blob: {entry.path}")
        target = Path(target).expanduser()
        if target.is_symlink():
            raise SnapshotError("restore target must not be a symlink")
        target = target.resolve()
        if target.exists() and not target.is_dir():
            raise SnapshotError("restore target must be a directory")
        if target.exists() and any(target.iterdir()):
            raise SnapshotError("restore target must be empty")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_target = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent)
        )
        promoted = False
        try:
            for entry in manifest.entries:
                blob = self._blob(entry)
                destination = temporary_target / entry.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(blob, destination)
                os.chmod(destination, entry.mode)
            receipt = self.verify(manifest, temporary_target)
            if not receipt.verified:
                raise SnapshotError("restored snapshot failed integrity verification")
            if target.exists():
                target.rmdir()
            os.replace(temporary_target, target)
            promoted = True
        finally:
            if not promoted:
                shutil.rmtree(temporary_target, ignore_errors=True)
        return SnapshotReceipt(
            operation="restore",
            before_digest=manifest.root_digest,
            after_digest=receipt.after_digest,
            verified=True,
            added=receipt.added,
            removed=receipt.removed,
            changed=receipt.changed,
        )

    def collect_garbage(
        self,
        keep_latest: int = 2,
        *,
        reachable_snapshot_ids: Iterable[str] = (),
        journal: "TransactionJournal | Path | None" = None,
        max_deletes: int | None = None,
    ) -> GarbageCollectionResult:
        """Remove only unreachable snapshots and their orphaned blobs.

        The retention floor is the newest ``keep_latest`` manifests, plus
        snapshots named by the current pointer, pending staging manifests,
        explicit reachability roots, and every record in an open journal.
        ``max_deletes`` bounds one pass so a maintenance tick cannot turn into
        an unbounded destructive sweep.  A malformed manifest, pointer, or
        journal fails closed before anything is deleted.
        """
        if not isinstance(keep_latest, int) or isinstance(keep_latest, bool):
            raise ValueError("keep_latest must be a non-negative integer")
        if keep_latest < 0:
            raise ValueError("keep_latest must be a non-negative integer")
        if max_deletes is not None and (
            not isinstance(max_deletes, int)
            or isinstance(max_deletes, bool)
            or max_deletes < 0
        ):
            raise ValueError("max_deletes must be a non-negative integer")
        manifests: dict[str, SnapshotManifest] = {}
        manifest_mtimes: dict[str, tuple[int, str]] = {}
        if self.manifests.exists():
            if self.manifests.is_symlink() or not self.manifests.is_dir():
                raise SnapshotError("snapshot manifest store is invalid")
            for path in self.manifests.iterdir():
                if path.name.startswith(".") or path.suffix != ".json":
                    continue
                if path.is_symlink() or not path.is_file():
                    raise SnapshotError(
                        "snapshot manifest store contains invalid entry"
                    )
                snapshot_id = path.stem
                _validate_snapshot_id(snapshot_id)
                manifests[snapshot_id] = self.load(snapshot_id)
                manifest_mtimes[snapshot_id] = (path.stat().st_mtime_ns, snapshot_id)

        protected: set[str] = set()
        for snapshot_id in reachable_snapshot_ids:
            _validate_snapshot_id(snapshot_id)
            protected.add(snapshot_id)
        protected.update(self._pointer_snapshot_ids())
        protected.update(self._staged_snapshot_ids())
        if journal is not None:
            source = (
                journal
                if isinstance(journal, TransactionJournal)
                else TransactionJournal(Path(journal))
            )
            for record in source.records():
                protected.update(_snapshot_ids_in_value(record.payload))

        newest = sorted(
            manifests,
            key=lambda snapshot_id: manifest_mtimes[snapshot_id],
            reverse=True,
        )[:keep_latest]
        retained = protected | set(newest)
        candidates = sorted(
            (snapshot_id for snapshot_id in manifests if snapshot_id not in retained),
            key=lambda snapshot_id: manifest_mtimes[snapshot_id],
        )
        if max_deletes is not None:
            candidates = candidates[:max_deletes]
        # Validate the complete blob directory before deleting any manifest;
        # GC must fail closed rather than leave a partially collected store.
        if self.blobs.exists():
            if self.blobs.is_symlink() or not self.blobs.is_dir():
                raise SnapshotError("snapshot blob store is invalid")
            for path in self.blobs.iterdir():
                if path.name.startswith(".") or len(path.name) != 64:
                    continue
                _validate_digest(path.name)
                if path.is_symlink() or not path.is_file():
                    raise SnapshotError("snapshot blob store contains invalid entry")
        for snapshot_id in candidates:
            (self.manifests / f"{snapshot_id}.json").unlink()
        if candidates:
            _fsync_directory(self.manifests)

        remaining = {
            snapshot_id: manifest
            for snapshot_id, manifest in manifests.items()
            if snapshot_id not in candidates
        }
        reachable_blobs = {
            entry.digest
            for manifest in remaining.values()
            for entry in manifest.entries
        }
        removed_blobs: list[str] = []
        if self.blobs.exists():
            if self.blobs.is_symlink() or not self.blobs.is_dir():
                raise SnapshotError("snapshot blob store is invalid")
            blob_candidates = []
            for path in self.blobs.iterdir():
                if path.name.startswith(".") or len(path.name) != 64:
                    continue
                _validate_digest(path.name)
                if path.is_symlink() or not path.is_file():
                    raise SnapshotError("snapshot blob store contains invalid entry")
                if path.name not in reachable_blobs:
                    blob_candidates.append(path.name)
            blob_candidates.sort()
            blob_budget = (
                None if max_deletes is None else max(0, max_deletes - len(candidates))
            )
            if blob_budget is not None:
                blob_candidates = blob_candidates[:blob_budget]
            for digest in blob_candidates:
                (self.blobs / digest).unlink()
                removed_blobs.append(digest)
            if removed_blobs:
                _fsync_directory(self.blobs)
        return GarbageCollectionResult(
            tuple(sorted(candidates)),
            tuple(removed_blobs),
            tuple(sorted(remaining)),
        )

    # Both spellings are useful to callers while the CLI boundary is kept out
    # of this deliberately local primitive.
    garbage_collect = collect_garbage
    gc = collect_garbage

    def _pointer_snapshot_ids(self) -> set[str]:
        path = self.root.parent / "current.json"
        if not path.exists():
            return set()
        if path.is_symlink():
            raise TransactionError("current pointer is invalid")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            result = set()
            for key in ("current", "previous"):
                snapshot_id = value.get(key)
                if snapshot_id is not None:
                    _validate_snapshot_id(snapshot_id)
                    result.add(snapshot_id)
            return result
        except (OSError, TypeError, ValueError, SnapshotError) as exc:
            raise TransactionError("current pointer is invalid") from exc

    def _staged_snapshot_ids(self) -> set[str]:
        staging = self.root.parent / "staging"
        if not staging.exists():
            return set()
        if staging.is_symlink() or not staging.is_dir():
            raise TransactionError("staging store is invalid")
        result = set()
        for path in staging.iterdir():
            if path.name.startswith(".") or path.suffix != ".json":
                continue
            if path.is_symlink() or not path.is_file():
                raise TransactionError("staging store contains invalid entry")
            snapshot_id = path.stem
            _validate_snapshot_id(snapshot_id)
            result.add(snapshot_id)
        return result


def snapshot_tree_from_entries(entries: Iterable[SnapshotEntry]) -> str:
    ordered = sorted(entries, key=lambda entry: entry.path)
    if len({entry.path for entry in ordered}) != len(ordered):
        raise SnapshotError("snapshot contains duplicate paths")
    return hashlib.sha256(
        _canonical([entry.to_dict() for entry in ordered])
    ).hexdigest()


def _validate_manifest(manifest: SnapshotManifest) -> None:
    if not isinstance(manifest, SnapshotManifest):
        raise SnapshotError("snapshot manifest is malformed")
    _validate_snapshot_id(manifest.snapshot_id)
    if not isinstance(manifest.entries, tuple):
        raise SnapshotError("snapshot entries must be a tuple")
    for entry in manifest.entries:
        if not isinstance(entry, SnapshotEntry):
            raise SnapshotError("snapshot entry is malformed")
        _validate_entry_path(entry.path)
        _validate_digest(entry.digest)
        if (
            not isinstance(entry.size_bytes, int)
            or isinstance(entry.size_bytes, bool)
            or entry.size_bytes < 0
            or not isinstance(entry.mode, int)
            or isinstance(entry.mode, bool)
            or entry.mode < 0
            or entry.mode > 0o7777
        ):
            raise SnapshotError("snapshot entry has invalid size or mode")
    if snapshot_tree_from_entries(manifest.entries) != manifest.snapshot_id:
        raise SnapshotError("snapshot manifest digest mismatch")


@dataclass(frozen=True)
class JournalRecord:
    sequence: int
    event: str
    payload: Mapping[str, object]
    previous_hash: str
    record_hash: str

    @property
    def mutation(self) -> "MutationReceipt | None":
        if self.event != "mutation":
            return None
        try:
            return MutationReceipt.from_dict(self.payload)
        except (TypeError, ValueError, KeyError):
            return None


@dataclass(frozen=True)
class MutationReceipt:
    """Intent and before/after evidence carried by one mutation record."""

    intent: str
    actor: str
    snapshot_before: str | None
    snapshot_after: str | None
    fencing_token: str
    result: Mapping[str, Any] | str

    def __post_init__(self) -> None:
        for field_name in ("intent", "actor", "fencing_token"):
            value = str(getattr(self, field_name)).strip()
            if not value or "\n" in value:
                raise ValueError(f"{field_name} must be a single non-empty line")
            object.__setattr__(self, field_name, value)
        for field_name in ("snapshot_before", "snapshot_after"):
            snapshot_id = getattr(self, field_name)
            if snapshot_id is not None:
                try:
                    _validate_snapshot_id(snapshot_id)
                except SnapshotError as exc:
                    raise ValueError(
                        f"{field_name} must be a valid snapshot id"
                    ) from exc
        if isinstance(self.result, Mapping):
            object.__setattr__(
                self, "result", json.loads(json.dumps(self.result, sort_keys=True))
            )
        elif not str(self.result).strip():
            raise ValueError("result must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": JOURNAL_SCHEMA,
            "intent": self.intent,
            "actor": self.actor,
            "snapshot_before": self.snapshot_before,
            "snapshot_after": self.snapshot_after,
            "fencing_token": self.fencing_token,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "MutationReceipt":
        if value.get("schema") not in (None, JOURNAL_SCHEMA):
            raise ValueError("unsupported journal schema")
        return cls(
            intent=str(value["intent"]),
            actor=str(value["actor"]),
            snapshot_before=value.get("snapshot_before"),
            snapshot_after=value.get("snapshot_after"),
            fencing_token=str(value["fencing_token"]),
            result=value["result"],
        )

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


class TransactionJournal:
    """Append-only, hash-chained JSONL receipts."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def records(self) -> tuple[JournalRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[JournalRecord] = []
        previous = "0" * 64
        raw = self.path.read_bytes()
        chunks = raw.splitlines(keepends=True)
        for index, chunk in enumerate(chunks):
            is_trailing_partial = index == len(chunks) - 1 and not chunk.endswith((
                b"\n",
                b"\r",
            ))
            if not chunk.strip():
                if is_trailing_partial:
                    break
                raise JournalError("journal hash chain is invalid")
            try:
                line = chunk.decode("utf-8")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("journal record must be an object")
                value_schema = value.get("schema")
                if value_schema not in (None, JOURNAL_SCHEMA):
                    raise ValueError("unsupported journal schema")
                payload = value["payload"]
                body = {
                    "sequence": value["sequence"],
                    "event": value["event"],
                    "payload": payload,
                    "previous_hash": value["previous_hash"],
                }
                if value_schema is not None:
                    body["schema"] = value_schema
                record_hash = hashlib.sha256(_canonical(body)).hexdigest()
                if (
                    value["sequence"] != len(records) + 1
                    or value["previous_hash"] != previous
                    or value["record_hash"] != record_hash
                    or not isinstance(payload, dict)
                ):
                    raise ValueError
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if is_trailing_partial:
                    break
                raise JournalError("journal hash chain is invalid") from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise JournalError("journal hash chain is invalid") from exc
            if (
                not isinstance(value["sequence"], int)
                or isinstance(value["sequence"], bool)
                or not isinstance(value["event"], str)
                or not value["event"]
                or "\n" in value["event"]
                or not isinstance(value["previous_hash"], str)
                or not isinstance(value["record_hash"], str)
            ):
                raise JournalError("journal hash chain is invalid")
            record = JournalRecord(
                len(records) + 1, str(value["event"]), payload, previous, record_hash
            )
            records.append(record)
            previous = record_hash
        return tuple(records)

    def append(self, event: str, payload: Mapping[str, object]) -> JournalRecord:
        if not event or "\n" in event:
            raise JournalError("journal event must be a single non-empty line")
        existing = self.records()
        self._discard_partial_tail()
        body = {
            "schema": JOURNAL_SCHEMA,
            "sequence": len(existing) + 1,
            "event": event,
            "payload": dict(payload),
            "previous_hash": existing[-1].record_hash if existing else "0" * 64,
        }
        record_hash = hashlib.sha256(_canonical(body)).hexdigest()
        value = {**body, "record_hash": record_hash}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            offset = 0
            while offset < len(encoded):
                offset += os.write(descriptor, encoded[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.path.parent)
        return JournalRecord(
            body["sequence"], event, dict(payload), body["previous_hash"], record_hash
        )

    def _discard_partial_tail(self) -> None:
        """Recover space occupied by a crash-truncated final JSON line."""
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        if not raw or raw.endswith((b"\n", b"\r")):
            return
        tail = raw.rsplit(b"\n", 1)[-1]
        try:
            json.loads(tail.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            with self.path.open("r+b") as handle:
                handle.truncate(len(raw) - len(tail))
        else:
            with self.path.open("ab") as handle:
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(self.path.parent)

    def append_mutation(
        self,
        *,
        intent: str,
        actor: str,
        snapshot_before: str | None,
        snapshot_after: str | None,
        fencing_token: str,
        result: Mapping[str, Any] | str,
    ) -> JournalRecord:
        """Append the canonical #338 mutation receipt as one journal record."""
        receipt = MutationReceipt(
            intent,
            actor,
            snapshot_before,
            snapshot_after,
            fencing_token,
            result,
        )
        return self.append("mutation", receipt.to_dict())


@dataclass(frozen=True)
class PointerRecord:
    current: str
    previous: str | None = None


class UpdateTransaction:
    """Stage immutable snapshots and atomically switch a current pointer."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.snapshots = SnapshotStore(self.root / "snapshots")
        self.staging = self.root / "staging"
        self.pointer_path = self.root / "current.json"
        self.journal = TransactionJournal(self.root / "journal.jsonl")

    def current(self) -> PointerRecord | None:
        if not self.pointer_path.exists():
            return None
        try:
            value = json.loads(self.pointer_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            if value.get("schema") != "simplicio.pointer/v1":
                raise ValueError
            current = str(value["current"])
            previous = value.get("previous")
            if previous is not None:
                previous = str(previous)
            self.snapshots.load(current)
            if previous is not None:
                self.snapshots.load(previous)
            return PointerRecord(current, previous)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise TransactionError("current pointer is invalid") from exc

    def stage(self, source: Path) -> SnapshotManifest:
        manifest = self.snapshots.create(Path(source))
        self.staging.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.staging / f"{manifest.snapshot_id}.json", manifest.to_dict())
        self.journal.append("stage", {"snapshot": manifest.snapshot_id})
        return manifest

    def activate(
        self,
        manifest: SnapshotManifest,
        *,
        health_check: Callable[[SnapshotManifest], bool] | None = None,
    ) -> PointerRecord:
        pending = self.staging / f"{manifest.snapshot_id}.json"
        if not pending.is_file():
            raise TransactionError("snapshot is not staged")
        old = self.current()
        candidate = PointerRecord(manifest.snapshot_id, old.current if old else None)
        _atomic_json(
            self.pointer_path,
            {
                "schema": "simplicio.pointer/v1",
                "current": candidate.current,
                "previous": candidate.previous,
            },
        )
        self.journal.append(
            "activate",
            {"before": old.current if old else None, "after": candidate.current},
        )
        if health_check is not None:
            try:
                healthy = bool(health_check(manifest))
            except Exception:
                healthy = False
            if not healthy:
                if old is None:
                    self.pointer_path.unlink(missing_ok=True)
                else:
                    self._write_pointer(PointerRecord(old.current, old.previous))
                self.journal.append(
                    "rollback",
                    {
                        "before": candidate.current,
                        "after": old.current if old else None,
                    },
                )
                raise TransactionError("candidate health check failed; rolled back")
        pending.unlink(missing_ok=True)
        self.journal.append("commit", {"snapshot": candidate.current})
        return candidate

    def rollback(self) -> PointerRecord:
        current = self.current()
        if current is None or current.previous is None:
            raise TransactionError("no previous snapshot is available for rollback")
        record = PointerRecord(current.previous, current.current)
        self._write_pointer(record)
        self.journal.append(
            "rollback", {"before": current.current, "after": record.current}
        )
        return record

    def _write_pointer(self, record: PointerRecord) -> None:
        _atomic_json(
            self.pointer_path,
            {
                "schema": "simplicio.pointer/v1",
                "current": record.current,
                "previous": record.previous,
            },
        )


__all__ = [
    "Equivalence",
    "GarbageCollectionResult",
    "JOURNAL_SCHEMA",
    "JournalError",
    "JournalRecord",
    "MutationReceipt",
    "PointerRecord",
    "RECEIPT_SCHEMA",
    "SnapshotEntry",
    "SnapshotError",
    "SnapshotManifest",
    "SnapshotReceipt",
    "SNAPSHOT_SCHEMA",
    "SnapshotStore",
    "TransactionError",
    "TransactionJournal",
    "UpdateTransaction",
    "shadow_equivalence",
    "snapshot_tree",
]
