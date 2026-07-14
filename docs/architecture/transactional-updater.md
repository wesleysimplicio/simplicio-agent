# Bounded transactional updater contract

`hermes_cli.transactional_updater.TransactionalUpdater` is the local façade
for issue #316. It composes the existing dirty-tree, snapshot/pointer,
detached-restart, and live-commit-attestation interfaces under one explicit
state root. The façade is deliberately shadow-only: it does not fetch a
release, mutate a live installation, stop a process, start a gateway, or
publish an artifact.

## Contract

1. `preserve()` inspects tracked and untracked paths, captures the patch and
   file blobs in a content-addressed store, enforces file/byte bounds, and
   emits a verified preservation receipt before staging.
2. `stage()` snapshots the candidate through `UpdateTransaction`; when a
   preservation is supplied, it applies the preserved changes in a disposable
   copy and reports conflicts without changing the checkout.
3. `activate()` atomically replaces the current pointer while retaining the
   previous snapshot. `rollback()` restores that previous pointer. Both
   transitions emit hash-chained receipts in `receipts.jsonl`.
4. `restart()` runs the detached helper with injected drain, supervisor, and
   startup callbacks. The helper owns no process termination operation;
   callback results are recorded as restart receipts.
5. `attest()` and `attest_rollback()` consume observations from the live
   supervisor and preserve the existing fail-closed rollback intent. They do
   not claim that the live gateway was changed.

The state root is caller-selected and should be outside the checkout. A
restart or kill can call `recover()` to re-read the durable pointer; it is
safe to call repeatedly. Receipt records are local evidence only and are not
signatures or release authorization.

## Verification boundary

Focused tests cover dirty-tree capture, bounded staging, pointer retention and
rollback, idempotent recovery, detached restart ordering, and failed live
attestation. The following remain `UNVERIFIED|` in this slice:

- OS matrix across clean Windows, macOS, and Linux filesystems;
- a real process killed during update and subsequent restart recovery;
- a live gateway restart and live commit observation;
- fetching, signing, or publishing an actual update artifact.
