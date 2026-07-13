# Architecture issue backlog reference

## Issue body contract

Use this order for architecture issues:

1. **Context** — what exists today and what was measured or observed.
2. **Objective** — one independently deliverable architectural outcome.
3. **Design** — schemas, ownership, state transitions, or boundaries.
4. **Step by step** — numbered implementation sequence, including migration and tests.
5. **Acceptance criteria** — unchecked, observable, mechanically verifiable items.
6. **Evidence required** — receipts, tests, benchmarks, re-query, or artifact paths.
7. **Dependencies** — parent epic, canonical contracts, and cross-repo ordering.
8. **Out of scope** — prevent the issue from becoming an unbounded roadmap.

## Decomposition classes

For a Simplicio Agent/runtime architecture review, prefer these independent lanes:

- canonical task envelope and state machine;
- CLI actuator and MCP fallback boundary;
- write-set, ownership, leases, and dirty-tree protection;
- doctor identity and adapter/config health;
- scheduler backpressure and truthful capacity metrics;
- tiered memory, decay, consolidation, and provenance;
- transport-independent typed IPC events;
- golden-path E2E proof from request to delivery;
- documentation/routing consistency.

Do not create a duplicate issue when an existing epic or canonical contract already owns the subject. Instead, create a narrower implementable child issue and add a comment to the parent with the links.

## Creation and verification

Prepare one body file per issue, then create independent issues concurrently:

```bash
simplicio shell -- gh issue create \
  --repo OWNER/REPO \
  --title "[P1][Architecture] ..." \
  --body-file /tmp/issue-slug.md
```

Verify each result with the GitHub API or `gh issue view`: URL, title, `OPEN` state, and the number of `- [ ]` acceptance criteria. Finally, comment on the parent epic/canonical contract with the decomposition links.

## Evidence language

Use measured repository/runtime observations in Context and mark unknowns as unverified. Do not claim issue creation until the returned GitHub URL and open state have been checked.
