"""Additional unit coverage for local-change staging (issue #343).

These tests target validation branches, error paths, and edge cases in
``hermes_cli.local_change_staging`` that the original real-git scenario
tests do not exercise: manifest/change-file validation, content-store
corruption handling, and stage/apply failure modes.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from hermes_cli.local_change_staging import (
    ChangeFile,
    ChangeStore,
    DirtyTree,
    LocalChangeManifest,
    ManifestIntegrityError,
    LocalChangeError,
    Preservation,
    apply_preserved,
    inspect_dirty,
    preserve,
    stage_ff_only,
    verify_preserved,
)

from tests.hermes_cli.test_local_change_staging import _git, _repo


def _preservation(manifest: LocalChangeManifest, patch_digest: str) -> Preservation:
    return Preservation(manifest, manifest.manifest_digest, patch_digest)


pytestmark = pytest.mark.live_system_guard_bypass


# ---------------------------------------------------------------------------
# ChangeFile.from_dict validation
# ---------------------------------------------------------------------------


def test_change_file_from_dict_rejects_bad_digest() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {"path": "a.txt", "status": "M ", "digest": "not-hex", "size_bytes": 1}
        )


def test_change_file_from_dict_rejects_absolute_path() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {"path": "/etc/passwd", "status": "M ", "digest": None, "size_bytes": 0}
        )


def test_change_file_from_dict_rejects_parent_traversal() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {"path": "../secret", "status": "M ", "digest": None, "size_bytes": 0}
        )


def test_change_file_from_dict_rejects_windows_drive_path() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {"path": "C:\\secret.txt", "status": "M ", "digest": None, "size_bytes": 0}
        )


def test_change_file_from_dict_rejects_empty_status() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {"path": "a.txt", "status": "", "digest": None, "size_bytes": 0}
        )


def test_change_file_from_dict_rejects_negative_size() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {"path": "a.txt", "status": "M ", "digest": None, "size_bytes": -1}
        )


def test_change_file_from_dict_rejects_bool_size() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {"path": "a.txt", "status": "M ", "digest": None, "size_bytes": True}
        )


def test_change_file_from_dict_rejects_bad_blob_digest() -> None:
    with pytest.raises(ManifestIntegrityError):
        ChangeFile.from_dict(
            {
                "path": "a.txt",
                "status": "M ",
                "digest": None,
                "size_bytes": 0,
                "blob_digest": "bogus",
            }
        )


def test_change_file_from_dict_accepts_valid_minimal_entry() -> None:
    entry = ChangeFile.from_dict(
        {"path": "a.txt", "status": "M ", "digest": None, "size_bytes": 0}
    )
    assert entry.path == "a.txt"
    assert entry.digest is None


# ---------------------------------------------------------------------------
# LocalChangeManifest.from_dict validation
# ---------------------------------------------------------------------------


_VALID_DIGEST = "a" * 64


def test_manifest_from_dict_rejects_wrong_schema() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict({"schema": "unknown"})


def test_manifest_from_dict_requires_base_commit() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(
            {
                "schema": "simplicio.local-changes/v1",
                "base_commit": "",
                "patch_digest": _VALID_DIGEST,
            }
        )


def test_manifest_from_dict_requires_valid_patch_digest() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(
            {
                "schema": "simplicio.local-changes/v1",
                "base_commit": "deadbeef",
                "patch_digest": "not-a-digest",
            }
        )


def test_manifest_from_dict_requires_files_and_hunks_lists() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(
            {
                "schema": "simplicio.local-changes/v1",
                "base_commit": "deadbeef",
                "patch_digest": _VALID_DIGEST,
                "files": "not-a-list",
                "hunks": [],
            }
        )


def test_manifest_from_dict_requires_non_empty_stash_strings() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(
            {
                "schema": "simplicio.local-changes/v1",
                "base_commit": "deadbeef",
                "patch_digest": _VALID_DIGEST,
                "files": [],
                "hunks": [],
                "stashes": [""],
            }
        )


def test_manifest_from_dict_rejects_malformed_file_entry() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(
            {
                "schema": "simplicio.local-changes/v1",
                "base_commit": "deadbeef",
                "patch_digest": _VALID_DIGEST,
                "files": ["not-a-mapping"],
                "hunks": [],
            }
        )


def test_manifest_from_dict_rejects_malformed_hunk_entry() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(
            {
                "schema": "simplicio.local-changes/v1",
                "base_commit": "deadbeef",
                "patch_digest": _VALID_DIGEST,
                "files": [],
                "hunks": ["not-a-mapping"],
            }
        )


def test_manifest_from_dict_rejects_hunk_with_bad_header() -> None:
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(
            {
                "schema": "simplicio.local-changes/v1",
                "base_commit": "deadbeef",
                "patch_digest": _VALID_DIGEST,
                "files": [],
                "hunks": [
                    {"path": "a.txt", "digest": _VALID_DIGEST, "header": "not-a-hunk"}
                ],
            }
        )


def test_manifest_from_dict_rejects_digest_mismatch() -> None:
    payload = {
        "schema": "simplicio.local-changes/v1",
        "base_commit": "deadbeef",
        "patch_digest": _VALID_DIGEST,
        "files": [],
        "hunks": [],
        "stashes": [],
        "manifest_digest": "b" * 64,
    }
    with pytest.raises(ManifestIntegrityError):
        LocalChangeManifest.from_dict(payload)


def test_manifest_round_trip_through_to_dict_and_from_dict() -> None:
    manifest = LocalChangeManifest("deadbeef", _VALID_DIGEST, (), ())
    restored = LocalChangeManifest.from_dict(manifest.to_dict())
    assert restored == manifest
    assert restored.manifest_digest == manifest.manifest_digest


def test_dirty_tree_dirty_property_true_and_false() -> None:
    empty = DirtyTree("deadbeef", (), ())
    assert empty.dirty is False
    with_stash = DirtyTree("deadbeef", (), ("stash@{0}",))
    assert with_stash.dirty is True
    with_file = DirtyTree(
        "deadbeef", (ChangeFile("a.txt", "M ", None, 0),), ()
    )
    assert with_file.dirty is True


# ---------------------------------------------------------------------------
# ChangeStore corruption / collision handling
# ---------------------------------------------------------------------------


def test_change_store_put_detects_collision(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    digest = store.put(b"hello")
    # Corrupt the stored object in place so its bytes no longer match its
    # own filename digest -- put() must detect the mismatch on a repeat put.
    (store.objects / digest).write_bytes(b"corrupted")
    with pytest.raises(ManifestIntegrityError):
        store.put(b"hello")


def test_change_store_get_missing_object_raises(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    with pytest.raises(ManifestIntegrityError):
        store.get("a" * 64)


def test_change_store_get_corrupted_object_raises(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    digest = store.put(b"hello")
    (store.objects / digest).write_bytes(b"tampered")
    with pytest.raises(ManifestIntegrityError):
        store.get(digest)


def test_change_store_save_manifest_detects_collision(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    manifest = LocalChangeManifest("deadbeef", _VALID_DIGEST, (), ())
    digest = manifest.manifest_digest
    store.manifests.mkdir(parents=True, exist_ok=True)
    (store.manifests / f"{digest}.json").write_bytes(b"not the real payload")
    with pytest.raises(ManifestIntegrityError):
        store.save_manifest(manifest)


def test_change_store_save_manifest_is_idempotent(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    manifest = LocalChangeManifest("deadbeef", _VALID_DIGEST, (), ())
    first = store.save_manifest(manifest)
    second = store.save_manifest(manifest)
    assert first == second


def test_change_store_load_manifest_missing_raises(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    with pytest.raises(ManifestIntegrityError):
        store.load_manifest("c" * 64)


def test_change_store_load_manifest_bad_json_raises(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    store.manifests.mkdir(parents=True, exist_ok=True)
    digest = "d" * 64
    (store.manifests / f"{digest}.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestIntegrityError):
        store.load_manifest(digest)


def test_change_store_load_manifest_rejects_non_mapping(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    digest = "e" * 64
    store.manifests.mkdir(parents=True, exist_ok=True)
    (store.manifests / f"{digest}.json").write_text(
        json.dumps([1, 2, 3]), encoding="utf-8"
    )
    with pytest.raises(ManifestIntegrityError):
        store.load_manifest(digest)


def test_change_store_load_manifest_detects_digest_mismatch(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    manifest = LocalChangeManifest("deadbeef", _VALID_DIGEST, (), ())
    real_digest = store.save_manifest(manifest)
    wrong_digest = "f" * 64
    store.manifests.mkdir(parents=True, exist_ok=True)
    (store.manifests / f"{wrong_digest}.json").write_bytes(
        (store.manifests / f"{real_digest}.json").read_bytes()
    )
    with pytest.raises(ManifestIntegrityError):
        store.load_manifest(wrong_digest)


def test_change_store_load_manifest_round_trip(tmp_path: Path) -> None:
    store = ChangeStore(tmp_path / "objects")
    manifest = LocalChangeManifest("deadbeef", _VALID_DIGEST, (), ())
    digest = store.save_manifest(manifest)
    restored = store.load_manifest(digest)
    assert restored == manifest


# ---------------------------------------------------------------------------
# stage_ff_only error paths
# ---------------------------------------------------------------------------


def test_stage_ff_only_rejects_existing_staging_path(tmp_path: Path) -> None:
    _bare, _seed, source = _repo(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(LocalChangeError):
        stage_ff_only(source, staging)


def test_stage_ff_only_rejects_malformed_upstream(tmp_path: Path) -> None:
    _bare, _seed, source = _repo(tmp_path)
    with pytest.raises(LocalChangeError):
        stage_ff_only(source, tmp_path / "staging", upstream="mainonly")


def test_stage_ff_only_reports_clone_failure(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    with pytest.raises(LocalChangeError):
        stage_ff_only(not_a_repo, tmp_path / "staging")


def test_stage_ff_only_skips_merge_when_already_up_to_date(tmp_path: Path) -> None:
    _bare, _seed, source = _repo(tmp_path)
    result = stage_ff_only(source, tmp_path / "staging")
    assert result.status == "ready"
    assert result.head == result.target


# ---------------------------------------------------------------------------
# apply_preserved / verify_preserved edge cases
# ---------------------------------------------------------------------------


def test_apply_preserved_rejects_patch_digest_mismatch(tmp_path: Path) -> None:
    _bare, _seed, source = _repo(tmp_path)
    (source / "app.txt").write_text("local one\nline two\n", encoding="utf-8")
    store = ChangeStore(tmp_path / "objects")
    preserved = preserve(source, store)
    tampered = dataclasses.replace(preserved, patch_digest="0" * 64)
    staged = stage_ff_only(source, tmp_path / "staging")
    with pytest.raises(ManifestIntegrityError):
        apply_preserved(staged.path, tampered, store)


def test_apply_preserved_conflicts_when_untracked_file_preexists_with_different_content(
    tmp_path: Path,
) -> None:
    _bare, _seed, source = _repo(tmp_path)
    (source / "new.txt").write_text("from source\n", encoding="utf-8")
    store = ChangeStore(tmp_path / "objects")
    preserved = preserve(source, store)
    staged = stage_ff_only(source, tmp_path / "staging")
    (staged.path / "new.txt").write_text("different content\n", encoding="utf-8")

    applied = apply_preserved(staged.path, preserved, store)
    assert applied.status == "blocked"
    assert "new.txt" in applied.conflicts


def test_verify_preserved_detects_blob_content_mismatch(tmp_path: Path) -> None:
    # Store a real, self-consistent blob, but record a manifest entry whose
    # digest/size deliberately do not describe that blob's real content.
    # ChangeStore.get() always re-validates what it hands back against the
    # digest it was asked for, so corrupting bytes on disk can never fool
    # verify_preserved(); the only way to exercise its own cross-check is an
    # internally inconsistent manifest like this one.
    store = ChangeStore(tmp_path / "objects")
    blob_digest = store.put(b"hello file")
    patch_digest = store.put(b"some patch bytes")
    bad_entry = ChangeFile(
        path="x.txt",
        status="M ",
        digest="a" * 64,
        size_bytes=999,
        blob_digest=blob_digest,
    )
    manifest = LocalChangeManifest(
        base_commit="deadbeef",
        patch_digest=patch_digest,
        files=(bad_entry,),
        hunks=(),
    )
    preservation = _preservation(manifest, patch_digest)
    assert verify_preserved(preservation, store) is False


def test_verify_preserved_continues_past_entries_without_blob(tmp_path: Path) -> None:
    _bare, seed, source = _repo(tmp_path)
    _git(source, "rm", "app.txt")
    store = ChangeStore(tmp_path / "objects")
    preserved = preserve(source, store)
    deleted = [f for f in preserved.manifest.files if f.path == "app.txt"][0]
    assert deleted.blob_digest is None
    assert verify_preserved(preserved, store) is True


def test_verify_preserved_detects_manifest_digest_mismatch(tmp_path: Path) -> None:
    _bare, _seed, source = _repo(tmp_path)
    (source / "app.txt").write_text("local one\nline two\n", encoding="utf-8")
    store = ChangeStore(tmp_path / "objects")
    preserved = preserve(source, store)
    tampered = dataclasses.replace(preserved, manifest_digest="9" * 64)
    assert verify_preserved(tampered, store) is False


# ---------------------------------------------------------------------------
# inspect_dirty rename handling
# ---------------------------------------------------------------------------


def test_inspect_dirty_reports_renamed_file_under_new_path(tmp_path: Path) -> None:
    _bare, _seed, source = _repo(tmp_path)
    _git(source, "mv", "app.txt", "renamed.txt")
    dirty = inspect_dirty(source)
    paths = {item.path for item in dirty.files}
    assert "renamed.txt" in paths
    assert "app.txt" not in paths
