---
manifest: native-supersede-sweep-2026-07.yaml
issue: 346
schema_version: 1
---

# Native supersede sweep — July 2026

This is a read-only governance artifact for the Wave 22 backlog.  The
machine-readable manifest is the source of truth and defines its scope
explicitly: 100% means every issue in `scope.issue_numbers` has exactly one
classification row.  It does not claim to enumerate issues that a live API
could not expose.

The verdict vocabulary is deliberately explicit:

* `superseded` means the scoped work is replaced by the named target issue(s);
* `subordinated` means the scoped work remains valid but is downstream of the
  named target issue(s); and
* `independent` means the scoped work remains a separate capability.

Issue #334 is listed as independent solely to make the boundary auditable. Its
graph-gate files are outside this slice and are not modified here.

## Acceptance-criteria mapping

Each row maps to one or more `AC-*` entries. The checker rejects unknown AC
identifiers, duplicate issue rows, out-of-scope rows, missing rows, and any
acceptance criterion that is never mapped. This prevents a bulk verdict from
silently hiding an unclassified issue.

## Evidence and mutation boundary

The local anti-bulk-close receipt is `VERIFIED`: `close_operations` is zero,
`per_issue_review_required` is true, and the checker exposes only manifest
reads and optional HTTP GET requests. No issue is closed, labeled, assigned, or
commented by this slice. A future operator must review each issue separately;
the manifest is not authorization for a bulk action.

`live_api`, owner assignment, and the 48-hour owner window are `UNVERIFIED` in
the checked-in artifact. They require a successful read-only API run and
time-stamped owner evidence. An `UNVERIFIED|` receipt is a limitation report,
not a successful live verification.

Run the deterministic check with:

```text
python scripts/check_supersede_sweep.py
```

An optional read-only API check is mockable in Python and can be requested with
`--github-repo owner/repo`. Network/API failures remain `UNVERIFIED|` and never
become mutation success.

## Ledger receipt contract

The manifest ledger is append-only and records the receipt ID, event, status,
and evidence. A valid local receipt proves only manifest integrity and the
absence of close operations. It does not prove issue ownership, a completed
48-hour review window, or that a GitHub state transition occurred.
