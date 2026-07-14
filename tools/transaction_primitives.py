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
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SnapshotError("snapshot entry has an invalid digest")


def _validate_snapshot_id(snapshot_id: str) -> None:
    if len(snapshot_id) != 64 or any(
        char not in "0123456789abcdef" for char in snapshot_id
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

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SnapshotEntry":
        try:
            entry = cls(
                str(value["path"]),
                str(value["digest"]),
                int(value["size_bytes"]),
                int(value["mode"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("snapshot entry is malformed") from exc
        _validate_entry_path(entry.path)
        _validate_digest(entry.digest)
        if entry.size_bytes < 0 or entry.mode < 0:
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
            if blob.exists() and blob.is_file():
                if _file_digest(blob)[0] == entry.digest:
                    continue
                blob.unlink()
            temporary = self.blobs / f".{entry.digest}.tmp"
            temporary.unlink(missing_ok=True)
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
        _validate_snapshot_id(snapshot_id)
        path = self.manifests / f"{snapshot_id}.json"
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
            blob = self.blobs / entry.digest
            if (
                not blob.is_file()
                or _file_digest(blob)[0] != entry.digest
                or _file_digest(blob)[1] != entry.size_bytes
            ):
                raise SnapshotError(f"missing or corrupt snapshot blob: {entry.path}")
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
            destination = target / entry.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob, destination)
            os.chmod(destination, entry.mode)
        receipt = self.verify(manifest, target)
        if not receipt.verified:
            raise SnapshotError("restored snapshot failed integrity verification")
        return SnapshotReceipt(
            operation="restore",
            before_digest=manifest.root_digest,
            after_digest=receipt.after_digest,
            verified=True,
            added=receipt.added,
            removed=receipt.removed,
            changed=receipt.changed,
        )


def snapshot_tree_from_entries(entries: Iterable[SnapshotEntry]) -> str:
    ordered = sorted(entries, key=lambda entry: entry.path)
    if len({entry.path for entry in ordered}) != len(ordered):
        raise SnapshotError("snapshot contains duplicate paths")
    return hashlib.sha256(
        _canonical([entry.to_dict() for entry in ordered])
    ).hexdigest()


def _validate_manifest(manifest: SnapshotManifest) -> None:
    _validate_snapshot_id(manifest.snapshot_id)
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
            if not chunk.strip():
                continue
            is_trailing_partial = index == len(chunks) - 1 and not chunk.endswith((
                b"\n",
                b"\r",
            ))
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
            except (
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                UnicodeDecodeError,
            ) as exc:
                if is_trailing_partial:
                    break
                raise JournalError("journal hash chain is invalid") from exc
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
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
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
