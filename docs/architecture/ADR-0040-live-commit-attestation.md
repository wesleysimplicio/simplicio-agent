# ADR-0040: bounded live-commit attestation and manual-pull detection

This bounded slice adds `tools/live_commit_attestation.py` as a pure boundary
for the updater/supervisor.  An update succeeds only when startup and health
are reported healthy and the live process reports both the expected Git commit
and the expected SHA-256 digest.  A missing or divergent report is `failed` and
contains an explicit rollback intent; after the caller restores the previous
slot, `attest_rollback` verifies the old live identity and reports
`rolled_back`.

The supervisor can feed authoritative checkout HEAD observations to
`detect_manual_pull`.  A changed HEAD is always `pending_update`, including a
change during an update in progress.  The in-flight update keeps its captured
HEAD, while the newly observed HEAD is staged through the normal gates instead
of being loaded directly by the live process.  The module does not start or
stop processes, perform Git operations, or claim that rollback was executed;
those effects remain owned by the updater/supervisor.

Focused evidence: `tests/tools/test_live_commit_attestation.py` covers expected
commit/digest success, startup and health failures, mismatch and rollback
attestation, deterministic loaded-code digesting, idle manual pulls, and a
manual pull during an active update.
