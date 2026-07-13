# Software Builder E2E foundation

Issue #151 has a bounded v1 seam in
[`tools/software_builder_manifest.py`](../../tools/software_builder_manifest.py).
It composes existing contracts instead of introducing a second task lifecycle:

```text
GoalContract → Mapper context → Dev CLI diff/test → Runtime gate/checkpoint/ledger
                                                     → Loop journal/watcher
```

The committed fixture is
[`fixtures/software-builder/v1-foundation.json`](../../fixtures/software-builder/v1-foundation.json).
It is host-independent and intentionally marked `fixture_only`. Its four
`receipt://software-builder/fixture/*` references are edges in the manifest,
not claims that those external producers ran. The same references are mirrored
in `GoalContract.evidence`, `TaskEnvelope.receipts`, and
`TaskEnvelope.evidence_refs`; the validator rejects a broken edge.

## Contract

- `GoalContract` owns the objective, acceptance criteria, evidence references,
  and the unsatisfied loop watcher.
- `TaskEnvelope` owns the lifecycle and stops at `evidence_ready`; it is not
  delivered or closed.
- Stages name the existing operators and their handoff shape: Mapper's
  `scan → inspect → handoff`, Dev CLI's deterministic task/edit, Runtime's
  `gate → checkpoint → ledger`, and the loop's `journal → watcher`.
- The backlog records dependencies, risks, and intended delivery artifacts.
- Measurement is `not_measured`; no token, retry, or edit-economy number is
  inferred from the fixture.

Validate it locally with:

```powershell
python tools/software_builder_manifest.py --validate fixtures/software-builder/v1-foundation.json
python -m pytest -q tests/tools/test_software_builder_manifest.py
```

## Explicit limits

This slice does not execute a clean-machine full-stack application, exercise a
browser/UI, build or publish a package, compare token economics, or prove that
the Runtime/Mapper/Dev CLI/Loop binaries are mutually compatible in a live
run. Those require producer receipts and delivery artifacts from a subsequent
issue/run. A receipt reference alone is never sufficient evidence for closing
that work.
