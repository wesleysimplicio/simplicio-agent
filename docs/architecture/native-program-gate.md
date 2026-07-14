# Native #314 parent integration gate

`native-program-gate.yaml` is the read-only, machine-readable contract for
the parent epic. It gives every child issue (#315–#323) a unique mapping to
its ADRs, implementation, focused tests, and reverse coverage in the existing
Native/P0 reconciliation graph.

Run the local contract gate from the repository root:

```text
python scripts/check_native_program.py
```

The gate verifies that all referenced files exist, rejects missing or
duplicate child mappings, and reports the live-process, release-artifact, and
rollback evidence as explicitly `UNVERIFIED|` until receipts are supplied.
`--require-ready` is the completion gate and intentionally fails while any of
those receipts remain unverified. An optional `--github-repo owner/repo`
performs read-only checks; the implementation accepts an injected fetcher so
tests can mock the API without network access or mutation.

This slice proves parent-program coverage only. It does not close #314, close
any child issue, claim a clean install, or claim that a live process has the
published digest.
