"""Focused real-git coverage for local-change staging (issue #343)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermes_cli.local_change_staging import (
    ChangeStore,
    apply_preserved,
    inspect_dirty,
    preserve,
    stage_ff_only,
    verify_preserved,
)


pytestmark = pytest.mark.live_system_guard_bypass


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    source = tmp_path / "source"
    subprocess.run(
        ["git", "init", "--bare", str(bare)], check=True, capture_output=True
    )
    subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
    _git(seed, "config", "user.email", "test@example.invalid")
    _git(seed, "config", "user.name", "Test")
    (seed / "app.txt").write_text("line one\nline two\n", encoding="utf-8")
    _git(seed, "add", "app.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "branch", "-M", "main")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-u", "origin", "main")
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    subprocess.run(
        ["git", "clone", str(bare), str(source)], check=True, capture_output=True
    )
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "Test")
    return bare, seed, source


def test_preserve_records_staged_unstaged_untracked_and_stash(tmp_path: Path) -> None:
    _bare, _seed, source = _repo(tmp_path)
    (source / "app.txt").write_text("local one\nline two\n", encoding="utf-8")
    (source / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(source, "add", "staged.txt")
    (source / "new.txt").write_bytes(b"new\x00bytes")
    staged_dirty = inspect_dirty(source)
    assert any(
        item.path == "staged.txt" and item.status == "A " for item in staged_dirty.files
    )
    _git(source, "stash", "push", "-m", "existing")
    # Recreate the dirty files after the pre-existing stash operation.
    (source / "app.txt").write_text("local one\nline two\n", encoding="utf-8")
    (source / "new.txt").write_bytes(b"new\x00bytes")

    dirty = inspect_dirty(source)
    assert {item.path for item in dirty.files} == {"app.txt", "new.txt"}
    assert dirty.stashes

    store = ChangeStore(tmp_path / "objects")
    result = preserve(source, store)
    assert result.manifest.schema == "simplicio.local-changes/v1"
    assert result.manifest.files[0].blob_digest
    assert result.manifest.hunks
    assert verify_preserved(result, store)


def test_compatible_changes_are_reapplied_to_ff_only_staging(tmp_path: Path) -> None:
    _bare, seed, source = _repo(tmp_path)
    (source / "app.txt").write_text("local one\nline two\n", encoding="utf-8")
    (source / "new.txt").write_text("untracked\n", encoding="utf-8")
    store = ChangeStore(tmp_path / "objects")
    preserved = preserve(source, store)

    (seed / "remote.txt").write_text("remote\n", encoding="utf-8")
    _git(seed, "add", "remote.txt")
    _git(seed, "commit", "-m", "remote")
    _git(seed, "push", "origin", "main")

    staged = stage_ff_only(source, tmp_path / "staging")
    assert staged.status == "ready"
    applied = apply_preserved(staged.path, preserved, store)
    assert applied.status == "applied"
    assert (staged.path / "app.txt").read_text(
        encoding="utf-8"
    ) == "local one\nline two\n"
    assert (staged.path / "remote.txt").read_text(encoding="utf-8") == "remote\n"
    assert (staged.path / "new.txt").read_text(encoding="utf-8") == "untracked\n"
    assert (source / "app.txt").read_text(encoding="utf-8") == "local one\nline two\n"


def test_conflict_is_blocked_and_original_patch_remains_recoverable(
    tmp_path: Path,
) -> None:
    _bare, seed, source = _repo(tmp_path)
    (source / "app.txt").write_text("local one\nline two\n", encoding="utf-8")
    store = ChangeStore(tmp_path / "objects")
    preserved = preserve(source, store)
    (seed / "app.txt").write_text("remote one\nline two\n", encoding="utf-8")
    _git(seed, "add", "app.txt")
    _git(seed, "commit", "-m", "remote conflict")
    _git(seed, "push", "origin", "main")

    staged = stage_ff_only(source, tmp_path / "staging")
    applied = apply_preserved(staged.path, preserved, store)
    assert applied.status == "blocked"
    assert "app.txt" in applied.conflicts
    assert verify_preserved(preserved, store)
    assert (source / "app.txt").read_text(encoding="utf-8") == "local one\nline two\n"


def test_divergent_upstream_does_not_mutate_authoritative_checkout(
    tmp_path: Path,
) -> None:
    _bare, seed, source = _repo(tmp_path)
    (source / "local-commit.txt").write_text("local\n", encoding="utf-8")
    _git(source, "add", "local-commit.txt")
    _git(source, "commit", "-m", "local divergence")
    before = _git(source, "rev-parse", "HEAD")

    (seed / "remote-commit.txt").write_text("remote\n", encoding="utf-8")
    _git(seed, "add", "remote-commit.txt")
    _git(seed, "commit", "-m", "remote divergence")
    _git(seed, "push", "origin", "main")

    result = stage_ff_only(source, tmp_path / "staging")
    assert result.status == "diverged"
    assert _git(source, "rev-parse", "HEAD") == before
    assert (source / "local-commit.txt").exists()
