# Mutation snapshot scope

This document freezes the bounded #338 slice. The implementation lives in
`tools/transaction_primitives.py`; it is deliberately a local primitive and
does not wire a CLI, updater, supervisor, lease store, or garbage collector.

## Included state

- An explicitly supplied directory, recursively collecting regular files.
- Relative POSIX paths, file bytes, file size, and permission mode.
- SHA-256 content-addressed blobs and a deterministic manifest root digest.
- Optional manifest metadata (`commit`, injected `timestamp`, and `signature`).
- A JSONL mutation journal with intent, actor, before/after snapshot IDs,
  fencing token, result, sequence, and a hash-chain link.

Manifest publication is atomic and happens only after every blob has been
written and re-read by digest. Existing blobs are reused only when their
digest still verifies. Restore checks every blob before writing and performs a
second tree comparison afterward. `verify_only=True` performs the comparison
without writing.

## Explicitly excluded state

SessionDB conversation history, caches, temporary files, symlinks, and any
state outside the supplied root are not captured. Symlinks are rejected rather
than followed. Snapshot GC, process restart, lease acquisition/fencing
integration, crash-kill orchestration, and user-facing commands are follow-up
boundaries.

## Journal recovery and receipts

Journal writes use append mode, a newline-delimited canonical JSON record, and
`flush`/`fsync`. A reader accepts all complete records and ignores only a
malformed final unterminated line, which represents a write interrupted by a
crash. The next append removes that incomplete tail before adding a new
record. Complete malformed or hash-chain-broken records fail closed.

Snapshot and mutation receipts contain only stable before/after digests and
sorted path differences. Their SHA-256 digest is therefore deterministic for
the same operation and evidence; wall-clock time is metadata supplied by the
caller, never an implicit part of the content address.
