"""Bounded local-change preservation and update staging primitives.

This module is intentionally a staging boundary.  It does not integrate with
the production updater or mutate the authoritative checkout.  A preservation
run records ``git diff HEAD --binary`` and relevant untracked files in a
content-addressed store before a separate clone is fetched and updated with
fast-forward-only semantics.  Reapplication reports conflicts instead of
discarding the original patch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Mapping, Sequence


LOCAL_CHANGES_SCHEMA = "simplicio.local-changes/v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_Runner = Callable[..., subprocess.CompletedProcess[bytes]]


class LocalChangeError(RuntimeError):
    """The local-change staging contract cannot safely continue."""


class ManifestIntegrityError(LocalChangeError):
    """A content-addressed patch or manifest is missing or corrupt."""


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_digest(value: object, name: str = "digest") -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ManifestIntegrityError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestIntegrityError("change path must be non-empty")
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ManifestIntegrityError("change path must stay within the repository")
    return posix.as_posix()


def _run_git(
    repo: Path, args: Sequence[str], *, runner: _Runner | None = None
) -> bytes:
    command = ["git", "-C", str(repo), *args]
    run = runner or subprocess.run
    result = run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise LocalChangeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


@dataclass(frozen=True)
class ChangeFile:
    """One dirty path and the digest of its pre-staging working-tree bytes."""

    path: str
    status: str
    digest: str | None
    size_bytes: int
    blob_digest: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "status": self.status,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "blob_digest": self.blob_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ChangeFile":
        path = _safe_path(value.get("path"))
        status = value.get("status")
        if not isinstance(status, str) or not status:
            raise ManifestIntegrityError("change file status must be non-empty")
        digest = value.get("digest")
        if digest is not None:
            _validate_digest(digest, "change file digest")
        blob_digest = value.get("blob_digest")
        if blob_digest is not None:
            _validate_digest(blob_digest, "change blob digest")
        size = value.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ManifestIntegrityError("change file size must be non-negative")
        return cls(path, status, digest, size, blob_digest)


@dataclass(frozen=True)
class PatchHunk:
    path: str
    digest: str
    header: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "digest": self.digest, "header": self.header}


@dataclass(frozen=True)
class LocalChangeManifest:
    """Versioned, content-addressed description of a dirty checkout."""

    base_commit: str
    patch_digest: str
    files: tuple[ChangeFile, ...]
    hunks: tuple[PatchHunk, ...]
    stashes: tuple[str, ...] = ()
    schema: str = LOCAL_CHANGES_SCHEMA

    def payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "base_commit": self.base_commit,
            "patch_digest": self.patch_digest,
            "files": [entry.to_dict() for entry in self.files],
            "hunks": [entry.to_dict() for entry in self.hunks],
            "stashes": list(self.stashes),
        }

    @property
    def manifest_digest(self) -> str:
        return _digest(_canonical(self.payload()))

    def to_dict(self) -> dict[str, object]:
        value = self.payload()
        value["manifest_digest"] = self.manifest_digest
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "LocalChangeManifest":
        if value.get("schema") != LOCAL_CHANGES_SCHEMA:
            raise ManifestIntegrityError("unsupported local-change manifest schema")
        base_commit = value.get("base_commit")
        if not isinstance(base_commit, str) or not base_commit:
            raise ManifestIntegrityError("manifest base_commit is required")
        patch_digest = _validate_digest(value.get("patch_digest"), "patch_digest")
        raw_files = value.get("files", [])
        raw_hunks = value.get("hunks", [])
        raw_stashes = value.get("stashes", [])
        if not isinstance(raw_files, list) or not isinstance(raw_hunks, list):
            raise ManifestIntegrityError("manifest files and hunks must be lists")
        if not isinstance(raw_stashes, list) or any(
            not isinstance(item, str) or not item for item in raw_stashes
        ):
            raise ManifestIntegrityError("manifest stashes must be non-empty strings")
        files: list[ChangeFile] = []
        for item in raw_files:
            if not isinstance(item, Mapping):
                raise ManifestIntegrityError("manifest file is malformed")
            files.append(ChangeFile.from_dict(item))
        hunks: list[PatchHunk] = []
        for item in raw_hunks:
            if not isinstance(item, Mapping):
                raise ManifestIntegrityError("manifest hunk is malformed")
            path = _safe_path(item.get("path"))
            digest = _validate_digest(item.get("digest"), "hunk digest")
            header = item.get("header")
            if not isinstance(header, str) or not header.startswith("@@"):
                raise ManifestIntegrityError("hunk header is malformed")
            hunks.append(PatchHunk(path, digest, header))
        manifest = cls(
            base_commit, patch_digest, tuple(files), tuple(hunks), tuple(raw_stashes)
        )
        expected = value.get("manifest_digest")
        if expected is not None and expected != manifest.manifest_digest:
            raise ManifestIntegrityError("manifest digest mismatch")
        return manifest


@dataclass(frozen=True)
class DirtyTree:
    base_commit: str
    files: tuple[ChangeFile, ...]
    stashes: tuple[str, ...]

    @property
    def dirty(self) -> bool:
        return bool(self.files or self.stashes)


@dataclass(frozen=True)
class Preservation:
    manifest: LocalChangeManifest
    manifest_digest: str
    patch_digest: str


@dataclass(frozen=True)
class HunkResult:
    path: str
    digest: str
    status: str


@dataclass(frozen=True)
class ApplyResult:
    status: str
    hunks: tuple[HunkResult, ...]
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageResult:
    status: str
    path: Path
    head: str
    target: str | None = None
    reason: str = ""


class ChangeStore:
    """Filesystem object store keyed solely by SHA-256 content."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.manifests = self.root / "manifests"

    def put(self, content: bytes) -> str:
        digest = _digest(content)
        self.objects.mkdir(parents=True, exist_ok=True)
        destination = self.objects / digest
        if destination.exists():
            if destination.read_bytes() != content:
                raise ManifestIntegrityError("content-addressed object collision")
            return digest
        fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=self.objects)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return digest

    def get(self, digest: str) -> bytes:
        digest = _validate_digest(digest)
        path = self.objects / digest
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ManifestIntegrityError(
                "content-addressed object is unavailable"
            ) from exc
        if _digest(content) != digest:
            raise ManifestIntegrityError("content-addressed object digest mismatch")
        return content

    def save_manifest(self, manifest: LocalChangeManifest) -> str:
        self.manifests.mkdir(parents=True, exist_ok=True)
        digest = manifest.manifest_digest
        path = self.manifests / f"{digest}.json"
        if path.exists() and path.read_bytes() != _canonical(manifest.to_dict()):
            raise ManifestIntegrityError("manifest digest collision")
        if not path.exists():
            path.write_bytes(_canonical(manifest.to_dict()))
        return digest

    def load_manifest(self, digest: str) -> LocalChangeManifest:
        digest = _validate_digest(digest, "manifest digest")
        try:
            value = json.loads(
                (self.manifests / f"{digest}.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestIntegrityError("manifest is unavailable") from exc
        if not isinstance(value, Mapping):
            raise ManifestIntegrityError("manifest must be an object")
        manifest = LocalChangeManifest.from_dict(value)
        if manifest.manifest_digest != digest:
            raise ManifestIntegrityError("manifest digest mismatch")
        return manifest


def _parse_status(raw: bytes) -> list[tuple[str, str]]:
    values = raw.split(b"\0")
    result: list[tuple[str, str]] = []
    index = 0
    while index < len(values):
        value = values[index]
        index += 1
        if not value:
            continue
        decoded = value.decode("utf-8", "surrogateescape")
        if len(decoded) < 4:
            raise LocalChangeError("git status returned malformed porcelain output")
        status, path = decoded[:2], decoded[3:]
        if status[0] in "RC" or status[1] in "RC":
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[1]
            else:
                # Porcelain -z emits the old name as a second NUL-delimited
                # token for rename/copy entries.  The new path is the one
                # that must be represented in the preservation manifest.
                index += 1
        result.append((status, _safe_path(path)))
    return result


def _hunks(patch: bytes) -> tuple[PatchHunk, ...]:
    current = ""
    found: list[PatchHunk] = []
    lines = patch.splitlines(keepends=True)
    chunk: list[bytes] = []

    def finish() -> None:
        if chunk and current:
            found.append(
                PatchHunk(
                    current,
                    _digest(b"".join(chunk)),
                    chunk[0].decode("utf-8", "replace").rstrip(),
                )
            )

    for line in lines:
        if line.startswith(b"diff --git "):
            finish()
            chunk = []
            current = ""
        if line.startswith(b"+++ b/"):
            current = _safe_path(
                line[6:].decode("utf-8", "surrogateescape").rstrip("\r\n")
            )
        if line.startswith(b"@@"):
            finish()
            chunk = [line]
        elif chunk:
            chunk.append(line)
    finish()
    return tuple(found)


def inspect_dirty(repo: Path, *, runner: _Runner | None = None) -> DirtyTree:
    """Inspect tracked, untracked, and existing stash state without mutation."""
    repo = Path(repo).resolve()
    base = _run_git(repo, ["rev-parse", "HEAD"], runner=runner).decode().strip()
    status = _parse_status(
        _run_git(
            repo,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            runner=runner,
        )
    )
    files: list[ChangeFile] = []
    for code, path_text in status:
        path = repo / path_text
        digest: str | None = None
        size = 0
        if path.is_file() and not path.is_symlink():
            digest, size = _file_digest(path)
        files.append(ChangeFile(path_text, code, digest, size))
    stashes = tuple(
        line.decode("utf-8", "replace").split(" ", 1)[0]
        for line in _run_git(
            repo, ["stash", "list", "--format=%H %gs"], runner=runner
        ).splitlines()
        if line
    )
    return DirtyTree(base, tuple(files), stashes)


def preserve(
    repo: Path, store: ChangeStore, *, runner: _Runner | None = None
) -> Preservation:
    """Capture a dirty tree before any network operation."""
    repo = Path(repo).resolve()
    dirty = inspect_dirty(repo, runner=runner)
    patch = _run_git(
        repo, ["diff", "--binary", "--no-ext-diff", "HEAD", "--"], runner=runner
    )
    patch_digest = store.put(patch)
    files: list[ChangeFile] = []
    for item in dirty.files:
        blob_digest = None
        if item.digest is not None:
            blob_digest = store.put((repo / item.path).read_bytes())
        files.append(
            ChangeFile(
                item.path, item.status, item.digest, item.size_bytes, blob_digest
            )
        )
    manifest = LocalChangeManifest(
        dirty.base_commit, patch_digest, tuple(files), _hunks(patch), dirty.stashes
    )
    manifest_digest = store.save_manifest(manifest)
    return Preservation(manifest, manifest_digest, patch_digest)


def stage_ff_only(
    repo: Path,
    staging: Path,
    upstream: str = "origin/main",
    *,
    runner: _Runner | None = None,
) -> StageResult:
    """Clone ``repo`` and advance only when ``upstream`` is fast-forwardable."""
    repo = Path(repo).resolve()
    staging = Path(staging).resolve()
    if staging.exists():
        raise LocalChangeError("staging path must not already exist")
    staging.parent.mkdir(parents=True, exist_ok=True)
    run = runner or subprocess.run
    clone = run(
        ["git", "clone", "--no-local", str(repo), str(staging)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if clone.returncode:
        detail = clone.stderr.decode("utf-8", "replace").strip()
        raise LocalChangeError(f"git clone failed: {detail}")
    if "/" not in upstream:
        raise LocalChangeError("upstream must be remote/ref, such as origin/main")
    remote, ref = upstream.split("/", 1)
    head = ""
    try:
        remote_url = (
            _run_git(repo, ["remote", "get-url", remote], runner=runner)
            .decode()
            .strip()
        )
        _run_git(staging, ["remote", "set-url", "origin", remote_url], runner=runner)
        head = _run_git(staging, ["rev-parse", "HEAD"], runner=runner).decode().strip()
        # Git's fetch command has no --ff-only flag on older supported
        # versions; fetching into the disposable clone followed by an
        # explicit --ff-only merge provides the same fail-closed semantics.
        _run_git(staging, ["fetch", "--no-tags", remote, ref], runner=runner)
        target = (
            _run_git(staging, ["rev-parse", "FETCH_HEAD"], runner=runner)
            .decode()
            .strip()
        )
        if head != target:
            _run_git(staging, ["merge", "--ff-only", "FETCH_HEAD"], runner=runner)
        head = _run_git(staging, ["rev-parse", "HEAD"], runner=runner).decode().strip()
        return StageResult("ready", staging, head, target)
    except LocalChangeError as exc:
        return StageResult("diverged", staging, head, reason=str(exc))


def apply_preserved(
    staging: Path,
    preservation: Preservation,
    store: ChangeStore,
    *,
    runner: _Runner | None = None,
) -> ApplyResult:
    """Apply a preserved patch and untracked blobs, reporting conflicts openly."""
    manifest = preservation.manifest
    patch = store.get(manifest.patch_digest)
    if _digest(patch) != preservation.patch_digest:
        raise ManifestIntegrityError("preserved patch digest mismatch")
    staging = Path(staging).resolve()
    patch_path = staging.parent / f".{staging.name}.local-changes.patch"
    patch_path.write_bytes(patch)
    try:
        run = runner or subprocess.run
        result = run(
            ["git", "-C", str(staging), "apply", "--3way", "--binary", str(patch_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        conflicts: list[str] = []
        if result.returncode:
            conflicts.extend(
                entry.path for entry in manifest.files if entry.status != "??"
            )
        hunk_status = tuple(
            HunkResult(
                entry.path,
                entry.digest,
                "conflict" if entry.path in conflicts else "applied",
            )
            for entry in manifest.hunks
        )
        for entry in manifest.files:
            if not entry.blob_digest:
                continue
            destination = staging / entry.path
            content = store.get(entry.blob_digest)
            if destination.exists():
                if destination.is_file() and destination.read_bytes() == content:
                    continue
                conflicts.append(entry.path)
                continue
            if entry.status == "??":
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            else:
                conflicts.append(entry.path)
        unique_conflicts = tuple(sorted(set(conflicts)))
        return ApplyResult(
            "blocked" if unique_conflicts else "applied", hunk_status, unique_conflicts
        )
    finally:
        patch_path.unlink(missing_ok=True)


def verify_preserved(preservation: Preservation, store: ChangeStore) -> bool:
    """Verify that the original patch and every captured file blob remain recoverable."""
    manifest = preservation.manifest
    patch = store.get(manifest.patch_digest)
    if _digest(patch) != manifest.patch_digest:
        return False
    for entry in manifest.files:
        if entry.blob_digest is None:
            continue
        content = store.get(entry.blob_digest)
        if entry.digest != _digest(content) or entry.size_bytes != len(content):
            return False
    return manifest.manifest_digest == preservation.manifest_digest


__all__ = [
    "ApplyResult",
    "ChangeFile",
    "ChangeStore",
    "DirtyTree",
    "HunkResult",
    "LOCAL_CHANGES_SCHEMA",
    "LocalChangeError",
    "LocalChangeManifest",
    "ManifestIntegrityError",
    "PatchHunk",
    "Preservation",
    "StageResult",
    "apply_preserved",
    "inspect_dirty",
    "preserve",
    "stage_ff_only",
    "verify_preserved",
]
