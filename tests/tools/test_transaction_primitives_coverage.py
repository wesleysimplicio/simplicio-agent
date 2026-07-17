"""Additional coverage for tools/transaction_primitives.py.

These tests target validation branches, crash/tamper paths, and edge cases
not already exercised by tests/tools/test_transaction_primitives.py.  Each
test is written to exercise real behavior (verified by locally mutating the
module under test during development and confirming the new test failed
before the fix/restoration), not merely to import a code path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.transaction_primitives import (
    JournalError,
    JournalRecord,
    MutationReceipt,
    PointerRecord,
    SnapshotEntry,
    SnapshotError,
    SnapshotManifest,
    SnapshotReceipt,
    SnapshotStore,
    TransactionError,
    TransactionJournal,
    UpdateTransaction,
    snapshot_tree,
    snapshot_tree_from_entries,
)
from tools import transaction_primitives as tp


def _tree(root: Path, value: str = "one") -> None:
    (root / "nested").mkdir(parents=True, exist_ok=True)
    (root / "app.txt").write_text(value, encoding="utf-8")
    (root / "nested" / "mode.sh").write_text("#!/bin/sh\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# low level validators
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["", "/abs/path", "C:\\abs", "..", "a/../b"],
)
def test_validate_entry_path_rejects_escapes(path):
    with pytest.raises(SnapshotError, match="root"):
        tp._validate_entry_path(path)


def test_validate_entry_path_accepts_normal_relative_path():
    tp._validate_entry_path("nested/file.txt")  # must not raise


@pytest.mark.parametrize("digest", ["short", "z" * 64, 123, None])
def test_validate_digest_rejects_bad_values(digest):
    with pytest.raises(SnapshotError, match="digest"):
        tp._validate_digest(digest)


@pytest.mark.parametrize("value", ["short", "z" * 64, 123])
def test_validate_snapshot_id_rejects_bad_values(value):
    with pytest.raises(SnapshotError, match="invalid snapshot id"):
        tp._validate_snapshot_id(value)


def test_optional_text_rejects_blank_but_allows_none():
    assert tp._optional_text(None) is None
    assert tp._optional_text(" x ") == "x"
    with pytest.raises(SnapshotError, match="non-empty"):
        tp._optional_text("   ")


# ---------------------------------------------------------------------------
# SnapshotEntry / SnapshotManifest (de)serialization
# ---------------------------------------------------------------------------


def test_snapshot_entry_from_dict_rejects_bool_size_and_bad_mode():
    base = {"path": "a", "digest": "a" * 64, "size_bytes": 1, "mode": 0o644}
    with pytest.raises(SnapshotError, match="malformed"):
        SnapshotEntry.from_dict({**base, "size_bytes": True})
    with pytest.raises(SnapshotError, match="malformed"):
        SnapshotEntry.from_dict({**base, "mode": True})
    with pytest.raises(SnapshotError, match="invalid size or mode"):
        SnapshotEntry.from_dict({**base, "mode": 0o10000})
    with pytest.raises(SnapshotError, match="invalid size or mode"):
        SnapshotEntry.from_dict({**base, "size_bytes": -1})
    with pytest.raises(SnapshotError, match="malformed"):
        SnapshotEntry.from_dict({"path": "a"})  # missing keys


def test_snapshot_manifest_from_dict_rejects_wrong_schema():
    with pytest.raises(SnapshotError, match="schema"):
        SnapshotManifest.from_dict({"schema": "nope"})


def test_snapshot_manifest_from_dict_rejects_non_list_entries():
    with pytest.raises(SnapshotError, match="entries must be a list"):
        SnapshotManifest.from_dict(
            {"schema": tp.SNAPSHOT_SCHEMA, "entries": {}, "snapshot_id": "a" * 64}
        )


def test_snapshot_manifest_from_dict_rejects_non_mapping_entry_item():
    with pytest.raises(SnapshotError, match="malformed"):
        SnapshotManifest.from_dict(
            {
                "schema": tp.SNAPSHOT_SCHEMA,
                "entries": ["not-a-mapping"],
                "snapshot_id": "a" * 64,
            }
        )


def test_snapshot_manifest_from_dict_rejects_duplicate_paths():
    entry = {"path": "a", "digest": "a" * 64, "size_bytes": 1, "mode": 0o644}
    # The duplicate-path check runs before the digest is validated, so any
    # syntactically valid snapshot_id reaches the code path under test.
    with pytest.raises(SnapshotError, match="duplicate"):
        SnapshotManifest.from_dict(
            {
                "schema": tp.SNAPSHOT_SCHEMA,
                "entries": [entry, entry],
                "snapshot_id": "a" * 64,
            }
        )


def test_snapshot_manifest_from_dict_rejects_root_digest_mismatch():
    entry = {"path": "a", "digest": "a" * 64, "size_bytes": 1, "mode": 0o644}
    real_id = snapshot_tree_from_entries((SnapshotEntry.from_dict(entry),))
    with pytest.raises(SnapshotError, match="root digest mismatch"):
        SnapshotManifest.from_dict(
            {
                "schema": tp.SNAPSHOT_SCHEMA,
                "entries": [entry],
                "snapshot_id": real_id,
                "root_digest": "b" * 64,
            }
        )


def test_snapshot_manifest_from_dict_rejects_digest_mismatch(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = snapshot_tree(source)
    value = manifest.to_dict()
    # Tamper with an entry's digest without recomputing snapshot_id.
    value["entries"][0]["digest"] = "f" * 64
    with pytest.raises(SnapshotError, match="manifest digest mismatch"):
        SnapshotManifest.from_dict(value)


def test_receipt_rejects_blank_or_multiline_operation():
    with pytest.raises(ValueError, match="operation"):
        SnapshotReceipt(operation="", before_digest=None, after_digest=None, verified=True)
    with pytest.raises(ValueError, match="operation"):
        SnapshotReceipt(
            operation="a\nb", before_digest=None, after_digest=None, verified=True
        )


def test_receipt_sorts_added_removed_changed():
    receipt = SnapshotReceipt(
        operation="verify",
        before_digest=None,
        after_digest=None,
        verified=False,
        added=("b", "a"),
        removed=("z", "y"),
        changed=("q", "p"),
    )
    assert receipt.added == ("a", "b")
    assert receipt.removed == ("y", "z")
    assert receipt.changed == ("p", "q")


# ---------------------------------------------------------------------------
# _snapshot_ids_in_value
# ---------------------------------------------------------------------------


def test_snapshot_ids_in_value_walks_nested_structures_and_ignores_junk():
    valid = "a" * 64
    also_valid = "b" * 64
    value = {
        "top": valid,
        "list": [also_valid, "not-a-snapshot-id", 42, None],
        "nested": {"deeper": [also_valid]},
    }
    found = tp._snapshot_ids_in_value(value)
    assert found == {valid, also_valid}


def test_snapshot_ids_in_value_returns_empty_for_scalar_or_invalid():
    assert tp._snapshot_ids_in_value(42) == set()
    assert tp._snapshot_ids_in_value("too-short") == set()
    assert tp._snapshot_ids_in_value(None) == set()


# ---------------------------------------------------------------------------
# _safe_files / snapshot_tree edge cases
# ---------------------------------------------------------------------------


def test_safe_files_rejects_non_directory_root(tmp_path: Path):
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    with pytest.raises(SnapshotError, match="real directory"):
        snapshot_tree(not_a_dir)


def test_safe_files_rejects_missing_root(tmp_path: Path):
    with pytest.raises(SnapshotError, match="real directory"):
        snapshot_tree(tmp_path / "does-not-exist")


def test_snapshot_id_survives_round_trip_when_top_level_name_sorts_after_subdir(
    tmp_path: Path,
):
    """Regression test for a real bug: snapshot_tree() previously computed
    the content-address digest over entries in os.walk() traversal order
    (a directory's own files before its subdirectories' files), while
    snapshot_tree_from_entries()/SnapshotManifest.from_dict()/_validate_manifest
    canonicalize by sorting entries on their full relative path. Whenever a
    top-level filename sorted alphabetically *after* a subdirectory name
    (e.g. "z_root.txt" vs "a_dir/file.txt"), the two orderings diverged and
    produced two different digests for the identical tree -- so a manifest
    written by SnapshotStore.create() would fail its own round-trip
    validation on load/restore. This must never happen: the round-trip
    (snapshot_tree -> to_dict -> from_dict, and store.create -> store.load)
    must always agree with each other and with snapshot_tree_from_entries.
    """
    root = tmp_path / "tree"
    root.mkdir()
    (root / "z_root.txt").write_text("root file that sorts last alphabetically at top level", encoding="utf-8")
    (root / "a_dir").mkdir()
    (root / "a_dir" / "file.txt").write_text("nested file under an early-sorting dir name", encoding="utf-8")

    manifest = snapshot_tree(root)
    assert manifest.snapshot_id == snapshot_tree_from_entries(manifest.entries)

    # The manifest must also survive the on-disk JSON round trip used by
    # every store operation (create -> to_dict -> load -> from_dict).
    reloaded = SnapshotManifest.from_dict(manifest.to_dict())
    assert reloaded.snapshot_id == manifest.snapshot_id

    store = SnapshotStore(tmp_path / "store")
    created = store.create(root)
    loaded = store.load(created.snapshot_id)
    assert loaded.snapshot_id == created.snapshot_id

    restored = tmp_path / "restored"
    receipt = store.restore(created, restored)
    assert receipt.verified


# ---------------------------------------------------------------------------
# SnapshotStore.load / _blob / create edge cases
# ---------------------------------------------------------------------------


def test_store_load_raises_on_symlinked_manifest(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = store.create(source)
    real_path = store.manifests / f"{manifest.snapshot_id}.json"
    real_path.unlink()
    try:
        other = tmp_path / "elsewhere.json"
        other.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
        real_path.symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(SnapshotError, match="unavailable"):
        store.load(manifest.snapshot_id)


def test_store_load_raises_on_invalid_json(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.manifests.mkdir(parents=True)
    bad_id = "a" * 64
    (store.manifests / f"{bad_id}.json").write_text("not json", encoding="utf-8")
    with pytest.raises(SnapshotError, match="unavailable"):
        store.load(bad_id)


def test_store_load_raises_on_non_dict_json(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.manifests.mkdir(parents=True)
    bad_id = "a" * 64
    (store.manifests / f"{bad_id}.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SnapshotError, match="unavailable"):
        store.load(bad_id)


def test_store_load_raises_when_filename_and_content_id_mismatch(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = store.create(source)
    # Copy the valid manifest content under a *different* filename.
    wrong_id = "b" * 64
    (store.manifests / f"{wrong_id}.json").write_text(
        json.dumps(manifest.to_dict()), encoding="utf-8"
    )
    with pytest.raises(SnapshotError, match="digest mismatch"):
        store.load(wrong_id)


def test_store_create_replaces_pre_existing_symlink_blob(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest_probe = snapshot_tree(source)
    digest = manifest_probe.entries[0].digest

    store.blobs.mkdir(parents=True)
    decoy = tmp_path / "decoy.txt"
    decoy.write_text("decoy", encoding="utf-8")
    try:
        (store.blobs / digest).symlink_to(decoy)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    manifest = store.create(source)
    blob_path = store.blobs / digest
    assert not blob_path.is_symlink()
    assert blob_path.read_bytes() == (source / manifest.entries[0].path).read_bytes()


def test_restore_raises_on_missing_blob(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = store.create(source)
    for entry in manifest.entries:
        (store.blobs / entry.digest).unlink()
    with pytest.raises(SnapshotError, match="missing or corrupt"):
        store.restore(manifest, tmp_path / "restored")


def test_restore_rejects_symlink_target(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = store.create(source)
    real_dir = tmp_path / "real-target"
    real_dir.mkdir()
    link = tmp_path / "link-target"
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(SnapshotError, match="symlink"):
        store.restore(manifest, link)


def test_restore_rejects_non_directory_target(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = store.create(source)
    target = tmp_path / "target-file"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(SnapshotError, match="must be a directory"):
        store.restore(manifest, target)


def test_restore_rejects_non_empty_target(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = store.create(source)
    target = tmp_path / "target-dir"
    target.mkdir()
    (target / "leftover.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SnapshotError, match="must be empty"):
        store.restore(manifest, target)


def test_restore_promotes_into_pre_existing_empty_directory(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    source = tmp_path / "source"
    source.mkdir()
    _tree(source)
    manifest = store.create(source)
    target = tmp_path / "target-dir"
    target.mkdir()
    receipt = store.restore(manifest, target)
    assert receipt.verified
    assert (target / "app.txt").exists()


# ---------------------------------------------------------------------------
# _validate_manifest direct exercises
# ---------------------------------------------------------------------------


def test_validate_manifest_rejects_non_manifest_instance():
    with pytest.raises(SnapshotError, match="malformed"):
        tp._validate_manifest("not-a-manifest")


def test_validate_manifest_rejects_entries_not_tuple():
    manifest = SnapshotManifest("a" * 64, [])
    with pytest.raises(SnapshotError, match="must be a tuple"):
        tp._validate_manifest(manifest)


def test_validate_manifest_rejects_non_entry_items():
    manifest = SnapshotManifest("a" * 64, ("not-an-entry",))
    with pytest.raises(SnapshotError, match="entry is malformed"):
        tp._validate_manifest(manifest)


def test_validate_manifest_rejects_bad_size_or_mode_bypassing_dataclass():
    entry = SnapshotEntry("a", "a" * 64, 1, 0o644)
    object.__setattr__(entry, "mode", -1)
    manifest = SnapshotManifest(
        snapshot_tree_from_entries((SnapshotEntry("a", "a" * 64, 1, 0o644),)),
        (entry,),
    )
    with pytest.raises(SnapshotError, match="invalid size or mode"):
        tp._validate_manifest(manifest)


def test_snapshot_tree_from_entries_rejects_duplicate_paths():
    entries = (
        SnapshotEntry("a", "a" * 64, 1, 0o644),
        SnapshotEntry("a", "b" * 64, 2, 0o644),
    )
    with pytest.raises(SnapshotError, match="duplicate"):
        snapshot_tree_from_entries(entries)


# ---------------------------------------------------------------------------
# GC validation branches
# ---------------------------------------------------------------------------


def test_gc_rejects_bad_keep_latest(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    with pytest.raises(ValueError, match="keep_latest"):
        store.collect_garbage(keep_latest=-1)
    with pytest.raises(ValueError, match="keep_latest"):
        store.collect_garbage(keep_latest=True)


def test_gc_rejects_bad_max_deletes(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    with pytest.raises(ValueError, match="max_deletes"):
        store.collect_garbage(max_deletes=-1)
    with pytest.raises(ValueError, match="max_deletes"):
        store.collect_garbage(max_deletes=True)


def test_gc_fails_closed_on_symlinked_manifests_dir(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.root.mkdir(parents=True)
    real = tmp_path / "real-manifests"
    real.mkdir()
    try:
        store.manifests.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(SnapshotError, match="invalid"):
        store.collect_garbage()


def test_gc_fails_closed_on_invalid_manifest_entry(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.manifests.mkdir(parents=True)
    (store.manifests / f"{'a' * 64}.json").mkdir()  # a directory, not a file
    with pytest.raises(SnapshotError, match="invalid entry"):
        store.collect_garbage()


def test_gc_fails_closed_on_symlinked_blobs_dir(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.root.mkdir(parents=True)
    real = tmp_path / "real-blobs"
    real.mkdir()
    try:
        store.blobs.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(SnapshotError, match="invalid"):
        store.collect_garbage()


def test_gc_fails_closed_on_invalid_blob_entry(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.blobs.mkdir(parents=True)
    (store.blobs / ("c" * 64)).mkdir()  # a directory, not a regular blob
    with pytest.raises(SnapshotError, match="invalid entry"):
        store.collect_garbage()


def test_gc_bounds_blob_deletion_with_max_deletes(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    manifests = []
    for index in range(2):
        source = tmp_path / f"source-{index}"
        source.mkdir()
        _tree(source, str(index))
        manifests.append(store.create(source))
    for index, manifest in enumerate(manifests, 1):
        os.utime(
            store.manifests / f"{manifest.snapshot_id}.json",
            ns=(index * 1_000_000_000, index * 1_000_000_000),
        )
    # keep_latest=0, no protections: both manifests are deletion candidates,
    # but max_deletes=1 must bound how many manifests and blobs go each pass.
    result = store.collect_garbage(keep_latest=0, max_deletes=1)
    assert len(result.removed_snapshots) == 1
    assert len(result.removed_blobs) <= 1


# ---------------------------------------------------------------------------
# pointer / staging reachability edge cases
# ---------------------------------------------------------------------------


def test_pointer_snapshot_ids_raises_on_symlinked_pointer(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.root.parent.mkdir(parents=True, exist_ok=True)
    pointer = store.root.parent / "current.json"
    real = tmp_path / "real-pointer.json"
    real.write_text("{}", encoding="utf-8")
    try:
        pointer.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(TransactionError, match="invalid"):
        store._pointer_snapshot_ids()


def test_pointer_snapshot_ids_raises_on_invalid_json(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.root.parent.mkdir(parents=True, exist_ok=True)
    (store.root.parent / "current.json").write_text("not json", encoding="utf-8")
    with pytest.raises(TransactionError, match="invalid"):
        store._pointer_snapshot_ids()


def test_pointer_snapshot_ids_returns_empty_set_without_pointer(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    assert store._pointer_snapshot_ids() == set()


def test_staged_snapshot_ids_raises_on_symlinked_staging_dir(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    store.root.parent.mkdir(parents=True, exist_ok=True)
    staging = store.root.parent / "staging"
    real = tmp_path / "real-staging"
    real.mkdir()
    try:
        staging.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(TransactionError, match="invalid"):
        store._staged_snapshot_ids()


def test_staged_snapshot_ids_raises_on_invalid_entry(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    staging = store.root.parent / "staging"
    staging.mkdir(parents=True)
    (staging / f"{'a' * 64}.json").mkdir()
    with pytest.raises(TransactionError, match="invalid entry"):
        store._staged_snapshot_ids()


def test_staged_snapshot_ids_returns_empty_set_without_staging_dir(tmp_path: Path):
    store = SnapshotStore(tmp_path / "store")
    assert store._staged_snapshot_ids() == set()


# ---------------------------------------------------------------------------
# JournalRecord.mutation
# ---------------------------------------------------------------------------


def test_journal_record_mutation_is_none_for_non_mutation_event():
    record = JournalRecord(1, "stage", {"snapshot": "a" * 64}, "0" * 64, "f" * 64)
    assert record.mutation is None


def test_journal_record_mutation_is_none_when_payload_is_malformed():
    record = JournalRecord(1, "mutation", {"intent": "x"}, "0" * 64, "f" * 64)
    assert record.mutation is None


# ---------------------------------------------------------------------------
# MutationReceipt validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["intent", "actor", "fencing_token"])
def test_mutation_receipt_rejects_blank_required_fields(field):
    kwargs = dict(
        intent="i",
        actor="a",
        snapshot_before=None,
        snapshot_after=None,
        fencing_token="1",
        result="ok",
    )
    kwargs[field] = "  "
    with pytest.raises(ValueError, match="non-empty"):
        MutationReceipt(**kwargs)


def test_mutation_receipt_rejects_invalid_snapshot_ids():
    with pytest.raises(ValueError, match="snapshot_before"):
        MutationReceipt(
            intent="i",
            actor="a",
            snapshot_before="short",
            snapshot_after=None,
            fencing_token="1",
            result="ok",
        )


def test_mutation_receipt_rejects_empty_string_result():
    with pytest.raises(ValueError, match="result"):
        MutationReceipt(
            intent="i",
            actor="a",
            snapshot_before=None,
            snapshot_after=None,
            fencing_token="1",
            result="   ",
        )


def test_mutation_receipt_from_dict_rejects_unsupported_schema():
    with pytest.raises(ValueError, match="schema"):
        MutationReceipt.from_dict(
            {
                "schema": "nope",
                "intent": "i",
                "actor": "a",
                "fencing_token": "1",
                "result": "ok",
            }
        )


# ---------------------------------------------------------------------------
# TransactionJournal crash/tamper edge cases
# ---------------------------------------------------------------------------


def test_journal_rejects_blank_line_in_the_middle(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    journal = TransactionJournal(path)
    journal.append("stage", {"snapshot": "a" * 64})
    with path.open("ab") as handle:
        handle.write(b"\n")  # blank line, not a trailing partial record
        handle.write(
            json.dumps({"event": "commit"}).encode("utf-8") + b"\n"
        )
    with pytest.raises(JournalError):
        journal.records()


def test_journal_rejects_non_dict_json_line(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    journal = TransactionJournal(path)
    with pytest.raises(JournalError):
        journal.records()


def test_journal_rejects_wrong_sequence_number(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    journal = TransactionJournal(path)
    journal.append("stage", {"snapshot": "a" * 64})
    text = path.read_text(encoding="utf-8")
    tampered = text.replace('"sequence":1', '"sequence":5')
    # record_hash won't match sequence 5 either way, but we want to hit the
    # sequence-mismatch branch specifically by keeping everything else valid.
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(JournalError):
        journal.records()


def test_journal_append_rejects_blank_or_multiline_event(tmp_path: Path):
    journal = TransactionJournal(tmp_path / "journal.jsonl")
    with pytest.raises(JournalError, match="single non-empty line"):
        journal.append("", {})
    with pytest.raises(JournalError, match="single non-empty line"):
        journal.append("a\nb", {})


def test_journal_discard_partial_tail_appends_newline_for_valid_json_without_newline(
    tmp_path: Path,
):
    path = tmp_path / "journal.jsonl"
    journal = TransactionJournal(path)
    journal.append("stage", {"snapshot": "a" * 64})
    complete_record = {
        "schema": tp.JOURNAL_SCHEMA,
        "sequence": 2,
        "event": "commit",
        "payload": {"snapshot": "b" * 64},
        "previous_hash": journal.records()[0].record_hash,
    }
    complete_record["record_hash"] = __import__("hashlib").sha256(
        tp._canonical(complete_record)
    ).hexdigest()
    # Write a *complete*, valid JSON record but withhold the trailing newline
    # to simulate a process that finished the write() but was killed before
    # the next append's newline-delimiter convention was reinforced.
    with path.open("ab") as handle:
        handle.write(json.dumps(complete_record, sort_keys=True).encode("utf-8"))
    assert not path.read_bytes().endswith(b"\n")

    # The tail is a *complete*, valid JSON record even without a trailing
    # newline, so records() parses it normally (this is not the truncation
    # path -- it exercises the "well-formed but newline-missing" tail).
    records = journal.records()
    assert len(records) == 2
    assert records[1].event == "commit"

    # append() calls _discard_partial_tail first, which must append the
    # missing newline (rather than truncate) because the tail parses as
    # valid JSON -- exercising the else-branch of _discard_partial_tail.
    journal.append("second-commit", {"snapshot": "c" * 64})
    records = journal.records()
    assert len(records) == 3
    assert records[2].event == "second-commit"
    assert path.read_bytes().count(b"\n") == 3


# ---------------------------------------------------------------------------
# UpdateTransaction edge cases
# ---------------------------------------------------------------------------


def test_current_rejects_non_dict_pointer(tmp_path: Path):
    transaction = UpdateTransaction(tmp_path / "state")
    transaction.root.mkdir(parents=True, exist_ok=True)
    transaction.pointer_path.write_text("[]", encoding="utf-8")
    with pytest.raises(TransactionError, match="invalid"):
        transaction.current()


def test_current_rejects_wrong_pointer_schema(tmp_path: Path):
    transaction = UpdateTransaction(tmp_path / "state")
    transaction.root.mkdir(parents=True, exist_ok=True)
    transaction.pointer_path.write_text(
        json.dumps({"schema": "nope", "current": "a" * 64}), encoding="utf-8"
    )
    with pytest.raises(TransactionError, match="invalid"):
        transaction.current()


def test_current_returns_none_without_pointer(tmp_path: Path):
    transaction = UpdateTransaction(tmp_path / "state")
    assert transaction.current() is None


def test_activate_raises_when_snapshot_not_staged(tmp_path: Path):
    transaction = UpdateTransaction(tmp_path / "state")
    manifest = SnapshotManifest("a" * 64, ())
    with pytest.raises(TransactionError, match="not staged"):
        transaction.activate(manifest)


def test_activate_treats_health_check_exception_as_unhealthy_and_rolls_back(
    tmp_path: Path,
):
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

    def _boom(_manifest):
        raise RuntimeError("health probe crashed")

    with pytest.raises(TransactionError, match="rolled back"):
        transaction.activate(second_manifest, health_check=_boom)
    assert transaction.current().current == first_manifest.snapshot_id


def test_activate_first_snapshot_with_failing_health_check_clears_pointer(
    tmp_path: Path,
):
    first = tmp_path / "first"
    first.mkdir()
    _tree(first, "one")
    transaction = UpdateTransaction(tmp_path / "state")
    manifest = transaction.stage(first)

    with pytest.raises(TransactionError, match="rolled back"):
        transaction.activate(manifest, health_check=lambda _m: False)
    assert transaction.current() is None
    assert not transaction.pointer_path.exists()


def test_rollback_raises_without_current_or_previous(tmp_path: Path):
    transaction = UpdateTransaction(tmp_path / "state")
    with pytest.raises(TransactionError, match="no previous snapshot"):
        transaction.rollback()

    first = tmp_path / "first"
    first.mkdir()
    _tree(first, "one")
    manifest = transaction.stage(first)
    transaction.activate(manifest)
    with pytest.raises(TransactionError, match="no previous snapshot"):
        transaction.rollback()
