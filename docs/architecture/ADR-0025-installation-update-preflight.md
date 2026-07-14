# ADR-0025: Installation and update preflight

Status: bounded slice for issue #342.

`hermes_cli/update_preflight.py` is the small boundary before an update may
mutate code. `detect_installation()` distinguishes a new target from an
existing code tree and records the existing install method (`git`, `pip`,
`docker`, or another stamped method) without contacting a package manager.

`UpdateLock` creates a durable lock file with `O_EXCL`. A second updater fails
closed, and stale locks are not reclaimed automatically: recovery must be an
explicit operator decision so two update processes cannot overlap.

`PreUpdateSnapshotStore` delegates hashing, blob storage, integrity checking,
restore, and `SnapshotReceipt` generation to
`tools.transaction_primitives.SnapshotStore`. It adds only the update-facing
installation metadata and persists it beside the content-addressed manifest.
With explicit metadata, the snapshot ID and receipt digest are deterministic;
timestamps are descriptive metadata and do not participate in the content
address. Release fetching, dependency synchronization, activation, restart,
and live commit attestation remain outside this slice and are unverified here.
