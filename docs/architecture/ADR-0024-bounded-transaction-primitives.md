# ADR-0024: bounded snapshot and update transaction primitives

Status: proposed slice for issues #315 and #316.

`tools/transaction_primitives.py` is the deliberately small local boundary for
transaction work. `snapshot_tree` produces a location-independent manifest of
sorted regular files; `SnapshotStore` stores file blobs by SHA-256 and verifies
the source again before publishing its manifest. `shadow_equivalence` compares
that manifest with a live tree without mutating either side, so a dirty tree or
shadow divergence is explicit and fail-closed.

`TransactionJournal` is append-only JSONL with a SHA-256 hash chain. An
`UpdateTransaction` stages an immutable snapshot, atomically replaces
`current.json`, retains the previous snapshot in the same pointer, and can
roll back after a failed health check. The module does not fetch releases,
restart processes, or claim a live gateway commit; those are separate
supervisor/release gates and remain intentionally unverified by this slice.
