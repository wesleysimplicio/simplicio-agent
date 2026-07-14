from pathlib import Path

import pytest

from tools.transaction_primitives import (
    JournalError,
    SnapshotError,
    SnapshotStore,
    TransactionError,
    TransactionJournal,
    UpdateTransaction,
    shadow_equivalence,
    snapshot_tree,
)


def _tree(root: Path, value: str = "one") -> None:
    (root / "nested").mkdir(parents=True, exist_ok=True)
    (root / "app.txt").write_text(value, encoding="utf-8")
    (root / "nested" / "mode.sh").write_text("#!/bin/sh\n", encoding="utf-8")


def test_snapshot_is_location_independent_and_shadow_equivalence_is_strict(
    tmp_path: Path,
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _tree(first)
    _tree(second)

    manifest = snapshot_tree(first)
    assert manifest.snapshot_id == snapshot_tree(second).snapshot_id
    assert shadow_equivalence(manifest, second).equivalent

    (second / "app.txt").write_text("changed", encoding="utf-8")
    result = shadow_equivalence(manifest, second)
    assert not result.equivalent
    assert result.changed == ("app.txt",)


def test_snapshot_rejects_symlink_and_store_round_trips(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    try:
        (source / "link").symlink_to(source / "app.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(SnapshotError, match="symlink"):
        snapshot_tree(source)

    (source / "link").unlink()
    store = SnapshotStore(tmp_path / "store")
    manifest = store.create(source)
    loaded = store.load(manifest.snapshot_id)
    restored = tmp_path / "restored"
    store.restore(loaded, restored)
    assert shadow_equivalence(manifest, restored).equivalent


def test_journal_hash_chain_detects_tampering(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    journal = TransactionJournal(path)
    journal.append("stage", {"snapshot": "a" * 64})
    journal.append("commit", {"snapshot": "a" * 64})
    assert len(journal.records()) == 2

    path.write_text(
        path.read_text(encoding="utf-8").replace('"commit"', '"tampered"'),
        encoding="utf-8",
    )
    with pytest.raises(JournalError):
        journal.records()


def test_update_transaction_preserves_previous_and_rolls_back(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _tree(first, "one")
    _tree(second, "two")
    transaction = UpdateTransaction(tmp_path / "state")

    first_manifest = transaction.stage(first)
    first_pointer = transaction.activate(first_manifest)
    second_manifest = transaction.stage(second)
    second_pointer = transaction.activate(second_manifest)
    assert second_pointer.current == second_manifest.snapshot_id
    assert second_pointer.previous == first_pointer.current
    assert transaction.current() == second_pointer

    rolled_back = transaction.rollback()
    assert rolled_back.current == first_manifest.snapshot_id
    assert rolled_back.previous == second_manifest.snapshot_id


def test_failed_health_check_restores_old_pointer(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _tree(first, "one")
    _tree(second, "two")
    transaction = UpdateTransaction(tmp_path / "state")
    first_manifest = transaction.stage(first)
    transaction.activate(first_manifest)
    second_manifest = transaction.stage(second)

    with pytest.raises(TransactionError, match="rolled back"):
        transaction.activate(second_manifest, health_check=lambda _: False)
    assert transaction.current().current == first_manifest.snapshot_id
