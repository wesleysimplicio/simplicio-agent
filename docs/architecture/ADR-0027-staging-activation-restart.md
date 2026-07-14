# ADR-0027: Validated staging, atomic `current`, and detached restart

- Status: bounded Native 2.3 slice
- Scope: `hermes_cli.staging_activation`
- Related issue: #344

## Decision

An updater may publish a candidate only after four independent receipts have
been produced while reading the staging directory: syntax, clean-interpreter
imports, config-schema validation, and the focused smoke fixture. Each gate
has its own result and optional log file. The focused smoke callback is
required; omitting it is a failed gate, so a caller cannot accidentally claim
that a smoke test ran.

Dependency synchronization is a decision, not an implicit side effect of
validation. `decide_lock_sync()` hashes the selected lockfiles in the staging
and active trees. Equal digests mean no package-manager invocation; different
digests mean the caller may synchronize the staging environment and then run
the import gate again. Installation detection, dirty-tree preservation, and
the package-manager invocation are outside this slice.

`AtomicCurrentPointer` copies a validated staging tree into a fresh immutable
slot, verifies its digest, and atomically replaces the `current` JSON record.
The previous slot remains available for rollback. Readers either observe the
old complete record or the new complete record; they do not observe a
partially-written pointer or a partially-copied slot. A staging tree changed
after validation is rejected before any pointer write.

Restart is represented by `DetachedRestartIntent`. The active process writes
that intent and launches `DetachedRestartHelper` in a new session/process
group. The helper waits for drain, asks the supervisor to restart, and waits
for startup health. Neither the launch boundary nor the helper calls
`terminate()`/`kill()` on the active process; supervisor ownership of process
lifetime is explicit.

## Non-goals

This contract does not detect installation type, acquire update leases, create
snapshots, fetch Git/remotes, preserve dirty files, run package managers, or
prove a live gateway commit attestation. Those responsibilities remain in
their owning updater slices. The module is intentionally usable with injected
config validators and deterministic smoke fixtures so CI can exercise the
contract without credentials or network access.

## Evidence

`tests/hermes_cli/test_staging_activation.py` covers the four gate receipts,
fail-closed smoke behavior, active-tree non-mutation, lock digest equality
and change, pointer replacement and post-validation mutation rejection, new
session spawning, ordered drain/supervisor/startup behavior, and failed-drain
short-circuiting.
