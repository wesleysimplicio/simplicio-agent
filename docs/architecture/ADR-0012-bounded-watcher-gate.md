# ADR-0012: bounded watcher-gate evidence boundary

**Status:** Accepted as a bounded slice (2026-07-13).  It does not complete
issue #21.

## Decision

`tools.watcher_gate` implements the deterministic core of the N-Nest rule:

```text
reported == recomputed
```

The implementation is original Simplicio code inspired by the N-Nest
principle described in [issue #21](https://github.com/wesleysimplicio/simplicio-agent/issues/21);
it does not copy source code from the referenced conceptual project.

The bounded API supports three local evidence shapes:

- `watch_file` resolves a path under an explicit workspace, then compares
  regular-file existence, byte size, and SHA-256.
- `watch_hash` hashes bytes, text, or canonical JSON and compares the digest.
- `watch_command` compares exit code and output SHA-256 using exactly one
  caller-injected recompute callback. It never starts a subprocess itself.

Matching evidence returns `Verdict.MEASURED`. A deterministic mismatch returns
`Verdict.FABRICATED` with a measured recomputation. Missing, unsafe, malformed,
or failed recomputation returns `Verdict.UNVERIFIED`, never a green result.

Operator consent is separate from observation. `authorize_action` accepts only
explicit consent from the depth-0 `operator`; a watcher or sub-agent cannot
authorize a mutation, escalation, or publication. The depth limit is a local
invariant and is not a claim about every existing agent recursion path.

## Deliberate limits

This slice does not claim real external verification. In particular, it does
not yet wire every `tools/` result through the gate, attach receipts to every
trajectory, install watcher callbacks in `agent/async_dag/` or delegation,
upgrade `background_review`/`curator` to emit these receipts, run actual
commands, sample long suites, or measure the F5 latency budget. Those are
follow-up integrations. The focused fake-injection suite proves only the
comparison boundary and its fail-closed behavior.
