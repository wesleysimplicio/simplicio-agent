# Mutation snapshot scope

This document freezes the bounded #338 slice. The implementation lives in
`tools/transaction_primitives.py`; it is deliberately a local primitive and
does not wire a CLI, updater, supervisor, or lease store.

## Included state

- An explicitly supplied directory, recursively collecting regular files.
- Relative POSIX paths, file bytes, file size, and permission mode.
- SHA-256 content-addressed blobs and a deterministic manifest root digest.
- Optional manifest metadata (`commit`, injected `timestamp`, and `signature`).
- A JSONL mutation journal with intent, actor, before/after snapshot IDs,
  fencing token, result, sequence, and a hash-chain link.
- A bounded `SnapshotStore.collect_garbage()` pass retaining the configured
  number of newest manifests plus current/previous pointers, staged snapshots,
  explicit roots, and all IDs referenced by the supplied open journal.

Manifest publication is atomic and happens only after every blob has been
written, re-read by digest, and the manifest directory entry is flushed where
the platform supports directory fsync. Existing blobs are reused only when
their digest still verifies; symlinked or non-regular objects are rejected.
Restore validates the complete manifest and every blob before writing, then
performs a second tree comparison afterward. `verify_only=True` performs the
comparison without writing.

## Explicitly excluded state

SessionDB conversation history, caches, temporary files, symlinks, and any
state outside the supplied root are not captured. Symlinks are rejected rather
than followed. Process restart, lease acquisition/fencing integration,
crash-kill orchestration, and user-facing commands are follow-up boundaries.
GC is intentionally bounded per call with `max_deletes`; it fails closed on a
malformed manifest, pointer, journal, or store entry and removes blobs only
when no retained manifest reaches them. The implementation does not claim a
live crash-kill or clean-machine durability proof.

## Journal recovery and receipts

Journal writes use append mode, a newline-delimited canonical JSON record, and
`flush`/`fsync` (plus a best-effort directory fsync). A reader accepts all
complete records and ignores only a malformed final unterminated JSON line,
which represents a write interrupted by a crash. The next append removes that
incomplete tail before adding a new record. A complete malformed or
hash-chain-broken record, including an unterminated record with valid JSON but
invalid fields, fails closed.

Snapshot and mutation receipts contain only stable before/after digests and
sorted path differences. Their SHA-256 digest is therefore deterministic for
the same operation and evidence; wall-clock time is metadata supplied by the
caller, never an implicit part of the content address.
