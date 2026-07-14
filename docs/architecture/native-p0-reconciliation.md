---
manifest: native-p0-reconciliation.yaml
epic_issue: 314
schema_version: 1
---

# Native/P0 reconciliation

This graph gives each open P0 issue exactly one relation to the Native
program.  The canonical machine-readable source is
[`native-p0-reconciliation.yaml`](native-p0-reconciliation.yaml); the gate
checks that source and the local #314 body snapshot.

| P0 issue | Relation | Native target(s) | Reason |
| --- | --- | --- | --- |
| #228 | `prerequisite` | #315, #319 | Establishes the single effect choke point before shadow-run or daemon compilation. |
| #209 | `prerequisite` | #316, #323 | Supplies the canonical state machine to the updater and release gate. |
| #221 | `prerequisite` | #319 | Defines Session/Turn/Tool boundaries for daemon compilation. |
| #220 | `subordinate` | #317, #323 | Supplies benchmark baselines to the governor and final release gate. |
| #222 | `subordinate` | #321 | Is absorbed by the native gateway with the legacy bridge isolated. |
| #210 | `subordinate` | #318, #319 | The capability broker and daemon absorb the CLI/kernel-binding boundary. |
| #211 | `subordinate` | #323 | Becomes the release-gate golden-path smoke test. |

The relation enum is intentionally small: `prerequisite`, `subordinate`, or
`superseded`.  No issue is closed by this local artifact.  GitHub owner
comments, API mutation, and CI execution remain `UNVERIFIED|` until an owner
publishes the relation block in #314 and comments each P0 issue.

Run locally:

```text
python scripts/check_program_graph.py
```

The checked-in body fixture is
[`native-p0-epic-314-body.md`](native-p0-epic-314-body.md).  A live,
read-only API check can be requested with `--github-repo`; failure to reach the
API is reported as `UNVERIFIED|` rather than treated as a successful mutation.
