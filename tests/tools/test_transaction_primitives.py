from pathlib import Path

import pytest

from tools.transaction_primitives import (
    JournalError,
    MutationReceipt,
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


def test_snapshot_manifest_metadata_is_not_part_of_content_address(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = SnapshotStore(tmp_path / "store")

    first = store.create(source, commit="abc", timestamp="2026-07-14T00:00:00Z")
    second = store.create(source, commit="def", timestamp="2026-07-15T00:00:00Z")

    assert first.root_digest == second.root_digest
    assert first.snapshot_id == second.snapshot_id
    assert store.load(first.snapshot_id).commit == "def"
    assert len(list((tmp_path / "store" / "blobs").iterdir())) == 2


def test_restore_verify_only_returns_deterministic_receipt_and_detects_drift(
    tmp_path: Path,
):
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = SnapshotStore(tmp_path / "store")
    manifest = store.create(source)
    restored = tmp_path / "restored"

    receipt = store.restore(manifest, restored)
    assert receipt.verified
    assert receipt.before_digest == manifest.root_digest
    assert receipt.digest() == store.restore(manifest, tmp_path / "restored-2").digest()

    (restored / "app.txt").write_text("drift", encoding="utf-8")
    check = store.restore(manifest, restored, verify_only=True)
    assert not check.verified
    assert check.changed == ("app.txt",)


def test_restore_rejects_corrupt_blob_before_writing_target(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    store = SnapshotStore(tmp_path / "store")
    manifest = store.create(source)
    blob = store.blobs / manifest.entries[0].digest
    blob.write_bytes(b"corrupt")

    with pytest.raises(SnapshotError, match="corrupt"):
        store.restore(manifest, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


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


def test_journal_mutation_receipt_and_truncated_tail_are_replay_safe(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    journal = TransactionJournal(path)
    record = journal.append_mutation(
        intent="update-config",
        actor="agent",
        snapshot_before="a" * 64,
        snapshot_after="b" * 64,
        fencing_token="17",
        result={"status": "committed", "files": ["config.yaml"]},
    )
    assert record.mutation == MutationReceipt(
        "update-config",
        "agent",
        "a" * 64,
        "b" * 64,
        "17",
        {"status": "committed", "files": ["config.yaml"]},
    )
    assert (
        record.mutation.digest()
        == MutationReceipt(
            "update-config",
            "agent",
            "a" * 64,
            "b" * 64,
            "17",
            {"files": ["config.yaml"], "status": "committed"},
        ).digest()
    )

    with path.open("ab") as handle:
        handle.write(b'{"sequence":2,"event":"mutation"')
    assert len(journal.records()) == 1
    journal.append("commit", {"snapshot": "b" * 64})
    assert [item.sequence for item in journal.records()] == [1, 2]


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
