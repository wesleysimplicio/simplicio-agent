# ADR-0014: Versioned Alias Registry

- Status: Accepted
- Date: 2026-07-13
- Issue: #193

## Context

Legacy command aliases still exist, but the bounded slice for issue `#193`
must not change CLI wiring or public namespace modules. We need an isolated
registry that can load alias metadata, map legacy names to canonical names,
surface deprecation ownership, and emit warning/receipt metadata without
capturing invocation arguments or secrets.

## Decision

Add `tools/alias_registry.py` as a standalone loader/validator with these
contracts:

1. Alias documents are JSON and versioned by
   `schema="simplicio-agent/alias-registry/v1"` plus `version=1`.
2. Each alias row declares `alias` and `canonical`.
3. Deprecated aliases additionally declare `owner`; optional `remove_after`
   sets the owner removal policy checkpoint.
4. Lookup operates only on `argv[0]`, not full argument payloads.
5. Warning metadata uses `simplicio-agent/alias-warning/v1`.
6. Receipt metadata uses `simplicio-agent/alias-receipt/v1` and stores only:
   invoked alias, canonical target, owner/deprecation fields, source, and
   `argv_count`.
7. Registry load is deterministic: files are read in sorted order and alias
   keys are normalized with trim + casefold.
8. Any duplicate or incompatible claim on the same normalized alias is a hard
   collision error.

## Schema

```json
{
  "schema": "simplicio-agent/alias-registry/v1",
  "version": 1,
  "aliases": [
    {
      "alias": "hermes",
      "canonical": "simplicio-agent",
      "deprecated": true,
      "owner": "cli",
      "warning_code": "deprecated_command_alias",
      "remove_after": "2027-01-01",
      "note": "legacy CLI alias"
    }
  ]
}
```

## Consequences

- Canonical legacy mapping is explicit and testable from fixture data.
- Removal accountability is attached to an owner instead of hidden in code.
- Receipts and warnings are safe to persist because they never contain raw
  args, tokens, or secrets.
- Future CLI wiring can consume this registry without reopening schema or
  collision semantics.
