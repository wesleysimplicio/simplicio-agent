# ADR-0025: native identity scan

The migration gate uses `tools/identity_scan.py` with the
`simplicio.identity-legacy-manifest/v1` inventory.  Every compatibility or
legal reference must declare its path, owner, reason, and (for compatibility)
an expiry.  Undeclared references and expired entries are blocking findings;
legal attribution is the only non-blocking classification.

`--no-legacy` is fail-closed and reports a stable SHA-256 digest of findings.
The scanner is source/package oriented and does not mutate the inventory or
silently carry a baseline forward.
