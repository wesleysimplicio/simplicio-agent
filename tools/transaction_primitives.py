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
from typing import Callable, Iterable, Mapping


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
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SnapshotError("snapshot entry has an invalid digest")


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
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


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


@dataclass(frozen=True)
class SnapshotManifest:
    snapshot_id: str
    entries: tuple[SnapshotEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "simplicio.snapshot/v1",
            "snapshot_id": self.snapshot_id,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class Equivalence:
    equivalent: bool
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()


def _file_digest(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    info = path.stat()
    return digest.hexdigest(), info.st_size, stat.S_IMODE(info.st_mode)


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

    def create(self, source: Path) -> SnapshotManifest:
        manifest = snapshot_tree(source)
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        for entry in manifest.entries:
            blob = self.blobs / entry.digest
            if not blob.exists():
                temporary = self.blobs / f".{entry.digest}.tmp"
                shutil.copyfile(Path(source).resolve() / entry.path, temporary)
                if _file_digest(temporary)[0] != entry.digest:
                    temporary.unlink(missing_ok=True)
                    raise SnapshotError("source changed while snapshotting")
                os.replace(temporary, blob)
        if snapshot_tree(source).snapshot_id != manifest.snapshot_id:
            raise SnapshotError("source changed while snapshotting")
        _atomic_json(
            self.manifests / f"{manifest.snapshot_id}.json", manifest.to_dict()
        )
        return manifest

    def load(self, snapshot_id: str) -> SnapshotManifest:
        if not snapshot_id or any(
            char not in "0123456789abcdef" for char in snapshot_id
        ):
            raise SnapshotError("invalid snapshot id")
        path = self.manifests / f"{snapshot_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            raw_entries = value.get("entries", [])
            if not isinstance(raw_entries, list):
                raise ValueError
            entries = tuple(
                SnapshotEntry(
                    str(item["path"]),
                    str(item["digest"]),
                    int(item["size_bytes"]),
                    int(item["mode"]),
                )
                for item in raw_entries
                if isinstance(item, dict)
            )
            if len(entries) != len(raw_entries):
                raise ValueError
            for entry in entries:
                _validate_entry_path(entry.path)
                _validate_digest(entry.digest)
                if entry.size_bytes < 0 or entry.mode < 0:
                    raise ValueError
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("snapshot manifest is unavailable") from exc
        if value.get("schema") != "simplicio.snapshot/v1":
            raise SnapshotError("unsupported snapshot schema")
        manifest = SnapshotManifest(str(value.get("snapshot_id")), entries)
        if (
            manifest.snapshot_id != snapshot_id
            or snapshot_tree_from_entries(entries) != snapshot_id
        ):
            raise SnapshotError("snapshot manifest digest mismatch")
        return manifest

    def restore(self, manifest: SnapshotManifest, target: Path) -> None:
        """Materialize a verified snapshot into a new or empty target directory."""
        for entry in manifest.entries:
            _validate_entry_path(entry.path)
            _validate_digest(entry.digest)
        target = Path(target).expanduser()
        if target.is_symlink():
            raise SnapshotError("restore target must not be a symlink")
        target = target.resolve()
        if target.exists() and not target.is_dir():
            raise SnapshotError("restore target must be a directory")
        if target.exists() and any(target.iterdir()):
            raise SnapshotError("restore target must be empty")
        target.mkdir(parents=True, exist_ok=True)
        for entry in manifest.entries:
            blob = self.blobs / entry.digest
            if not blob.is_file() or _file_digest(blob)[0] != entry.digest:
                raise SnapshotError(f"missing or corrupt snapshot blob: {entry.path}")
            destination = target / entry.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob, destination)
            os.chmod(destination, entry.mode)


def snapshot_tree_from_entries(entries: Iterable[SnapshotEntry]) -> str:
    ordered = sorted(entries, key=lambda entry: entry.path)
    return hashlib.sha256(
        _canonical([entry.to_dict() for entry in ordered])
    ).hexdigest()


@dataclass(frozen=True)
class JournalRecord:
    sequence: int
    event: str
    payload: Mapping[str, object]
    previous_hash: str
    record_hash: str


class TransactionJournal:
    """Append-only, hash-chained JSONL receipts."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def records(self) -> tuple[JournalRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[JournalRecord] = []
        previous = "0" * 64
        for expected_sequence, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            try:
                value = json.loads(line)
                payload = value["payload"]
                body = {
                    "sequence": value["sequence"],
                    "event": value["event"],
                    "payload": payload,
                    "previous_hash": value["previous_hash"],
                }
                record_hash = hashlib.sha256(_canonical(body)).hexdigest()
                if (
                    value["sequence"] != expected_sequence
                    or value["previous_hash"] != previous
                    or value["record_hash"] != record_hash
                    or not isinstance(payload, dict)
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise JournalError("journal hash chain is invalid") from exc
            record = JournalRecord(
                expected_sequence, str(value["event"]), payload, previous, record_hash
            )
            records.append(record)
            previous = record_hash
        return tuple(records)

    def append(self, event: str, payload: Mapping[str, object]) -> JournalRecord:
        if not event or "\n" in event:
            raise JournalError("journal event must be a single non-empty line")
        existing = self.records()
        body = {
            "sequence": len(existing) + 1,
            "event": event,
            "payload": dict(payload),
            "previous_hash": existing[-1].record_hash if existing else "0" * 64,
        }
        record_hash = hashlib.sha256(_canonical(body)).hexdigest()
        value = {**body, "record_hash": record_hash}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return JournalRecord(
            body["sequence"], event, dict(payload), body["previous_hash"], record_hash
        )


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
    "JournalError",
    "JournalRecord",
    "PointerRecord",
    "SnapshotEntry",
    "SnapshotError",
    "SnapshotManifest",
    "SnapshotStore",
    "TransactionError",
    "TransactionJournal",
    "UpdateTransaction",
    "shadow_equivalence",
    "snapshot_tree",
]
