# CI quality gates

Issue #349 has a bounded, deterministic merge gate for checks that can run
without provider credentials. The policy contract lives in
`.github/quality-gates.yml`; `.github/workflows/quality-gates.yml` runs the
required unit, local integration, security/authority, offline cost/latency,
coverage, and Windows diagnostics jobs, then fails its aggregate check unless
every required job is successful.

## Acceptance and evidence boundary

| Issue #349 criterion | Gate/evidence in this slice | Status boundary |
| --- | --- | --- |
| Required checks block merge | `quality-gates / All quality gates pass`; aggregate evaluates every required result | The workflow gate is blocking; hosted execution is not reproduced locally |
| Security or authority regression fails | Injection, trust-boundary, distributed-protocol, and autonomy-policy tests | Local test commands are MEASURED when run; hosted status is UNVERIFIED here |
| Cost and latency regressions compare to baseline | Cost-policy tests plus `tools.perf_gate.compare`; baseline path and threshold are policy-configured | The committed baseline is bootstrap/empty, so runner performance is UNVERIFIED |
| Every corrected bug has a regression test | Focused suites remain explicit in the gate commands | This slice cannot infer bug-to-test traceability for unrelated future changes |
| Execution/evaluation reports are available | Each required job uploads JUnit XML; cost and coverage upload JSON; aggregate uploads a summary JSON | Missing artifacts are visible as `UNVERIFIED`, not silently ignored |
| Main branch requires green pipeline | `ci.yml` includes the quality aggregate in `all-checks-pass` | Branch-protection settings are repository administration, not locally verifiable |

The coverage contract records a target of 85% global and 90% for critical
scopes (`agent`, `gateway`, and `hermes_cli`). This bounded workflow measures
the gate-contract suite and enforces its 85% threshold; complete product and
critical-scope coverage is explicitly `UNVERIFIED` until a dedicated,
baseline-backed measurement is added. `.coveragerc` enables branch coverage,
records missing lines, and keeps the threshold reviewable.

The cost gate exercises deterministic model-cost policy tests and the pure
baseline comparison contract. The committed baseline has no runner-captured
metrics, so no local run may claim a performance result; the workflow emits a
JSON receipt and reports bootstrap status as `UNVERIFIED` until a hosted runner
captures a reviewable baseline.

External provider E2E and long-running stress tests are deliberately not
required by this deterministic gate. They need credentials, services, or
runner capacity outside this slice and remain visible as
`availability: unavailable` / `status: UNVERIFIED`, never as passing E2E
evidence.

Branch protection should require the single `quality-gates / All quality gates
pass` check (the aggregate job), in addition to any repository-specific checks.
