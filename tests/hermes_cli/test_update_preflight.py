from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.update_preflight import (
    INSTALLATION_SCHEMA,
    LOCK_SCHEMA,
    PRE_UPDATE_SCHEMA,
    InstallationInfo,
    PreUpdateMetadataError,
    PreUpdateSnapshotStore,
    UpdateLock,
    UpdateLockError,
    acquire_update_lock,
    detect_installation,
)


def _tree(root: Path, value: str = "one") -> None:
    (root / "nested").mkdir(parents=True)
    (root / "app.txt").write_text(value, encoding="utf-8")
    (root / "nested" / "VERSION").write_text("1.0.0", encoding="utf-8")


def test_detects_new_and_existing_installation_types(tmp_path: Path) -> None:
    fresh = detect_installation(tmp_path / "new")
    assert fresh.is_new
    assert fresh.install_type == "unknown"

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    (checkout / ".install_method").write_text("git\n", encoding="utf-8")
    existing = detect_installation(checkout)
    assert existing.is_existing
    assert existing.install_type == "git"


def test_update_lock_is_exclusive_and_releases_on_exception(tmp_path: Path) -> None:
    path = tmp_path / "state" / "update.lock"
    with pytest.raises(UpdateLockError, match="already held"):
        with UpdateLock(path, token="first"):
            with UpdateLock(path, token="second"):
                pass
    assert not path.exists()

    with pytest.raises(RuntimeError):
        with UpdateLock(path, token="third"):
            raise RuntimeError("stop")
    assert not path.exists()


def test_lock_release_fails_closed_for_replaced_owner(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    lock = UpdateLock(path, token="owner-a")
    lock.acquire()
    path.write_text(
        json.dumps({"schema": "simplicio.update-lock/v1", "token": "owner-b"}),
        encoding="utf-8",
    )
    with pytest.raises(UpdateLockError, match="owner mismatch"):
        lock.release()
    path.unlink()


def test_pre_update_snapshot_persists_installation_metadata_and_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    install = InstallationInfo("existing", "git", tmp_path / "checkout", "1.0.0", "abc")
    store = PreUpdateSnapshotStore(tmp_path / "snapshots")
    first = store.create(
        source, install, commit="abc", timestamp="2026-07-14T00:00:00Z"
    )
    second = store.create(
        source, install, commit="abc", timestamp="2026-07-14T00:00:00Z"
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.receipt.digest() == second.receipt.digest()
    loaded = store.load(first.snapshot_id)
    assert loaded.installation == install
    assert loaded.manifest.commit == "abc"
    assert loaded.manifest.timestamp == "2026-07-14T00:00:00Z"


def test_restore_delegates_to_transaction_primitives_and_detects_drift(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = PreUpdateSnapshotStore(tmp_path / "snapshots")
    snapshot = store.create(
        source, InstallationInfo("new", "unknown", tmp_path / "new")
    )
    restored = tmp_path / "restored"
    receipt = store.restore(snapshot, restored)
    assert receipt.verified
    (restored / "app.txt").write_text("drift", encoding="utf-8")
    drift = store.restore(snapshot, restored, verify_only=True)
    assert not drift.verified
    assert drift.changed == ("app.txt",)


def test_locked_snapshot_uses_installation_commit_and_releases_lock(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = PreUpdateSnapshotStore(tmp_path / "snapshots")
    installation = InstallationInfo(
        "existing", "git", tmp_path / "checkout", commit="from-install"
    )
    lock_path = tmp_path / "update.lock"

    snapshot = store.create_locked(
        source,
        installation,
        lock_path,
        timestamp="2026-07-14T00:00:00Z",
    )

    assert snapshot.manifest.commit == "from-install"
    assert not lock_path.exists()


def test_missing_pre_update_metadata_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = PreUpdateSnapshotStore(tmp_path / "snapshots")
    snapshot = store.create(
        source, InstallationInfo("new", "unknown", tmp_path / "new")
    )
    (store.metadata / f"{snapshot.snapshot_id}.json").unlink()
    with pytest.raises(PreUpdateMetadataError):
        store.load(snapshot.snapshot_id)


# ---------------------------------------------------------------------------
# Coverage-gap tests (issue #342: close 80.35% -> target >=90%).
# Anti-tautology: each test below was verified to actually fail against the
# unmodified module logic (e.g. removing the guarded branch, or reverting to
# a version that swallows the error) before being trusted — see the PR
# description for the before/after coverage numbers.
# ---------------------------------------------------------------------------


def test_installation_info_rejects_invalid_state() -> None:
    with pytest.raises(ValueError, match="state must be new or existing"):
        InstallationInfo("bogus", "git", Path("/tmp/x"))


def test_installation_info_rejects_multiline_field() -> None:
    with pytest.raises(ValueError, match="must be a single line"):
        InstallationInfo("existing", "git\nmalicious", Path("/tmp/x"))
    with pytest.raises(ValueError, match="must be a single line"):
        InstallationInfo("existing", "git", Path("/tmp/x"), version="1.0\n2.0")


def test_installation_info_from_dict_rejects_wrong_schema() -> None:
    with pytest.raises(PreUpdateMetadataError, match="unsupported installation metadata schema"):
        InstallationInfo.from_dict({"schema": "not-the-real-schema"})


def test_installation_info_from_dict_rejects_missing_fields() -> None:
    with pytest.raises(PreUpdateMetadataError, match="malformed"):
        InstallationInfo.from_dict({"schema": INSTALLATION_SCHEMA})


def test_installation_info_from_dict_rejects_blank_optional_text() -> None:
    # An empty string for version/commit must be treated as malformed, not
    # silently coerced to None -- silently dropping bad metadata would hide
    # a corrupted snapshot record.
    with pytest.raises(PreUpdateMetadataError, match="malformed"):
        InstallationInfo.from_dict(
            {
                "schema": INSTALLATION_SCHEMA,
                "state": "existing",
                "install_type": "git",
                "root": "/tmp/x",
                "version": "   ",
                "commit": None,
            }
        )


def test_installation_info_from_dict_round_trips_with_none_optional_fields() -> None:
    info = InstallationInfo.from_dict(
        {
            "schema": INSTALLATION_SCHEMA,
            "state": "new",
            "install_type": "unknown",
            "root": "/tmp/x",
            "version": None,
            "commit": None,
        }
    )
    assert info.version is None
    assert info.commit is None


def test_read_version_prefers_root_version_file(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    info = detect_installation(root)
    assert info.version == "9.9.9"


def test_read_version_falls_back_to_pyproject_toml(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "2.3.4"\n', encoding="utf-8"
    )
    info = detect_installation(root)
    assert info.version == "2.3.4"


def test_read_commit_returns_none_when_no_git_dir(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    info = detect_installation(root)
    assert info.commit is None


def test_read_commit_resolves_symbolic_ref(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text("deadbeef123\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    info = detect_installation(root)
    assert info.commit == "deadbeef123"


def test_read_commit_returns_detached_head_hash(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    git = root / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text("cafebabe456\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    info = detect_installation(root)
    assert info.commit == "cafebabe456"


def test_detect_installation_falls_back_to_unknown_when_detector_raises(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    with patch(
        "hermes_cli.update_preflight.detect_install_method",
        side_effect=RuntimeError("boom"),
    ):
        info = detect_installation(root)
    assert info.install_type == "unknown"


def test_detect_installation_reclassifies_pip_as_git_when_git_dir_present(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    with patch(
        "hermes_cli.update_preflight.detect_install_method",
        return_value="pip",
    ):
        info = detect_installation(root)
    assert info.install_type == "git"


def test_lock_acquire_twice_on_same_instance_raises(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    lock = UpdateLock(path, token="same-instance")
    lock.acquire()
    try:
        with pytest.raises(UpdateLockError, match="already held by this owner"):
            lock.acquire()
    finally:
        lock.release()


def test_lock_release_without_acquire_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    lock = UpdateLock(path, token="never-acquired")
    # Must not raise and must not create the lock file.
    lock.release()
    assert not path.exists()


def test_lock_release_fails_closed_on_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    lock = UpdateLock(path, token="owner-x")
    lock.acquire()
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(UpdateLockError, match="cannot be verified for release"):
        lock.release()
    path.unlink()


def test_lock_acquire_cleans_up_on_write_failure(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    lock = UpdateLock(path, token="write-fails")
    with patch("hermes_cli.update_preflight.json.dump", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            lock.acquire()
    # The partially-written lock file must not be left behind -- a stranded
    # lock would fail-closed every future update attempt.
    assert not path.exists()
    assert not lock._held


def test_acquire_update_lock_helper_returns_held_lock(tmp_path: Path) -> None:
    path = tmp_path / "update.lock"
    lock = acquire_update_lock(path, token="helper")
    try:
        assert lock._held
        assert path.exists()
    finally:
        lock.release()


def test_snapshot_store_load_rejects_wrong_schema(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = PreUpdateSnapshotStore(tmp_path / "snapshots")
    snapshot = store.create(source, InstallationInfo("new", "unknown", tmp_path / "new"))
    metadata_path = store.metadata / f"{snapshot.snapshot_id}.json"
    metadata_path.write_text(json.dumps({"schema": "wrong/v1"}), encoding="utf-8")
    with pytest.raises(PreUpdateMetadataError):
        store.load(snapshot.snapshot_id)


def test_snapshot_store_load_rejects_snapshot_id_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = PreUpdateSnapshotStore(tmp_path / "snapshots")
    snapshot = store.create(source, InstallationInfo("new", "unknown", tmp_path / "new"))
    metadata_path = store.metadata / f"{snapshot.snapshot_id}.json"
    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    value["snapshot_id"] = "not-the-real-id"
    metadata_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PreUpdateMetadataError):
        store.load(snapshot.snapshot_id)


def test_snapshot_store_load_rejects_non_dict_installation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = PreUpdateSnapshotStore(tmp_path / "snapshots")
    snapshot = store.create(source, InstallationInfo("new", "unknown", tmp_path / "new"))
    metadata_path = store.metadata / f"{snapshot.snapshot_id}.json"
    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    value["installation"] = "not-a-dict"
    metadata_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PreUpdateMetadataError):
        store.load(snapshot.snapshot_id)
