# ADR-0033: bounded watcher-gate evidence boundary

**Status:** Accepted as a bounded slice (2026-07-21). It does not complete
issue #21 until the runtime-backed F5 latency evidence is available.

## Decision

`tools.watcher_gate` implements the deterministic core of the N-Nest rule:

```text
reported == recomputed
```

The implementation is original Simplicio code inspired by the N-Nest
principle described in [issue #21](https://github.com/wesleysimplicio/simplicio-agent/issues/21);
it does not copy source code from the referenced conceptual project.
The origin reference is the [N-Nest project](https://github.com/JesseBrown1980/N-Nest-Prime-INFINITE-SELF-REFLECT-AGENTS-NESTED),
used only as a conceptual source.

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

`watch_result_boundary` now provides the common return-boundary contract for
tool results and sub-agent results. The existing tool invocation pipeline
records its receipt in the outcome, ledger metadata, and trajectory adapter;
fabricated results are replaced with a safe blocked result. Delegation attaches
the same receipt to each child entry before aggregation. No independent
recomputation is reported as `UNVERIFIED`; deterministic equality is
`MEASURED` (or `CANON` when the caller marks the source canonical), and a
deterministic mismatch is `FABRICATED` and blocked at the tool boundary.

Existing `background_review` and `curator` remain the owners of their review
flows. Their structured watcher verdict is explicitly `UNVERIFIED` because a
model-authored review is not an independent recomputation; this avoids
duplicating reviewers or presenting model agreement as measured evidence.

## Deliberate limits

This slice does not claim real external verification. In particular, it does
not yet wire every `tools/` result through the gate, install a runtime-backed
recomputation callback for every deployment, integrate `agent/async_dag/`, run
actual commands, sample long suites, or measure the F5 latency budget. Those
are follow-up integrations. The focused fake-injection suite proves the
comparison boundary, non-recursive consent, propagation to tool receipts and
trajectories, delegation fail-closed behavior, and structured reviewer
verdicts. Runtime/F5 acceptance remains `UNVERIFIED` in this environment.
