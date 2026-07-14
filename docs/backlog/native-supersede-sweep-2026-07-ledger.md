# Native supersede sweep ledger

The ledger contract is `simplicio.backlog-supersede-ledger/v1`, embedded in
[`native-supersede-sweep-2026-07.yaml`](native-supersede-sweep-2026-07.yaml).
Entries are append-only receipts, never commands. A receipt records evidence
about a read-only observation; it cannot authorize closing, labeling,
assigning, or commenting on an issue.

| Receipt | Meaning | Status in this slice |
| --- | --- | --- |
| `local-read-only-sweep-v1` | One verdict per scoped issue; no close operation exists in the checker. | `VERIFIED` |
| live API receipt | Read-only issue state and comments were fetched successfully. | `UNVERIFIED` |
| owner-window receipt | An owner and a completed 48-hour review window were observed. | `UNVERIFIED` |

`UNVERIFIED|` is intentionally preserved when network, credentials, owner
assignment, or elapsed-time evidence is missing. It must not be rewritten as a
pass by a formatter or by a bulk-close automation.
