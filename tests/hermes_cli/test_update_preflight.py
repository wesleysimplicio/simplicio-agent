from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli.update_preflight import (
    InstallationInfo,
    PreUpdateMetadataError,
    PreUpdateSnapshotStore,
    UpdateLock,
    UpdateLockError,
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
