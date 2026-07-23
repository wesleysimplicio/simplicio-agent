# Issue #518: bounded internal-JSON scan

This receipt records the bounded scanner slice only. It does not claim that the
repository-wide binary migration or Runtime conformance work is complete.

## Measured run

Command:

```text
python scripts/check_internal_json.py --root . --inventory config/json-boundaries.toml
```

| Measure | Result |
| --- | ---: |
| Status | PASS |
| Candidate JSON files in configured roots | 207 |
| Exact registry entries | 214 |
| Unclassified findings | 0 |
| Focused unit tests | 3 passed |

The registry rejects globs, traversal paths, duplicate entries, missing owners or
reasons, and expired review dates. It is bounded by `max_files = 10000` and
`max_bytes = 4194304`; generated, source, fixture, and runtime-state roots are
listed explicitly in `config/json-boundaries.toml`.

## Remaining issue criteria

- UNVERIFIED| internal JSON has not been replaced by HBP/HBI/TOML across all producers and consumers.
- UNVERIFIED| unit, integration, system, cross-repository E2E, restart/recovery, migration, rollback, and mixed-version lanes.
- UNVERIFIED| HBI/HBP Runtime conformance and receipt lineage.
- UNVERIFIED| performance measurements and release/publish blocking.
- UNVERIFIED| external adapter boundary behavior beyond this inventory scan.
