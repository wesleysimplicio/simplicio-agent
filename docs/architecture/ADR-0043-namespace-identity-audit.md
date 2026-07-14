# ADR-0043: namespace and identity migration audit

- Status: accepted for the bounded issue #322 audit slice
- Date: 2026-07-14
- Related: issue #322, ADR-0023, ADR-0025

## Decision

`tools/namespace_identity_audit.py` is the evidence boundary for the
inside-out namespace migration.  It does not rename files or modify the
inventory.  The reviewed inventory is
`fixtures/identity/namespace-inventory.v1.json`, whose entries identify
canonical surfaces, temporary shims, temporary bridges, and known legacy
surfaces with an owner, reason, and expiry where applicable.

The scanner searches the same canonical and legacy terms across three
independent surfaces:

1. tracked/text source files (`scan_source`);
2. supplied wheel/zip/tar artifacts (`scan_build`); and
3. a redacted JSON runtime snapshot (`scan_runtime`).

`build_receipt` combines the independently sorted findings into
`simplicio.namespace-identity-receipt/v1`.  Receipt digests are SHA-256 over
canonical JSON and contain no timestamps, raw process arguments, or runtime
secrets.  Omitted build or runtime surfaces are explicitly
`unverified_surfaces`, never an implicit clean result.

## Gate semantics

An undeclared legacy consumer is blocking.  An inventoried shim, bridge, or
legacy surface is non-blocking for this audit slice but keeps
`migration_scope` at `UNVERIFIED` until the path is removed and a complete
source/build/runtime run has no remaining migration entries.  This preserves
the distinction between “the inventory is internally valid” and “identity
migration is complete.”

The current tree intentionally remains `UNVERIFIED`: the compatibility facade,
runtime bridge, and legacy implementation surfaces are still present.  A
future removal slice must update the inventory only after consumer search,
clean artifact inspection, and a live redacted snapshot prove that no
consumer remains.

## Usage

```text
python -m tools.namespace_identity_audit \
  --root . \
  --inventory fixtures/identity/namespace-inventory.v1.json \
  --build dist/simplicio_agent.whl \
  --runtime runtime-identity.json \
  --json
```

The runtime input is an operator-provided redacted snapshot; this slice does
not attach to or mutate a live process.  `--today YYYY-MM-DD` makes expiry
evaluation reproducible for archived receipts.

