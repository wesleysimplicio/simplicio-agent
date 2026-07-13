# Capability benchmark and release gate (issue #157)

This slice establishes the deterministic contract for a future cross-domain
benchmark. It does not claim that Simplicio Agent can complete any domain task
just because that task is listed.

## Versioned manifest

The checked-in manifest is
`fixtures/bench/capability/capability-manifest.v1.json`. Every task declares:

- setup and goal;
- constraints and risk mode;
- expected artifacts;
- verifier and timeout;
- whether it belongs to the PR smoke subset;
- optional capability/permission/secret requirements.

The manifest includes declarations for desktop, browser, coding, media,
office (document/spreadsheet/PDF), mobile, and persistent-run (crash/resume).
Those are coverage declarations only until a result receipt proves execution.

## Evidence semantics

Every result metric has an `evidence_kind`:

| Kind | Meaning | Can satisfy release `task_success`? |
| --- | --- | --- |
| `measured` | Produced by executing the task in the labeled environment | Yes |
| `replay` | Replayed from a preserved prior run | No |
| `benchmark` | Imported/comparison benchmark data | No |
| `estimated` | Inferred or predicted without task execution | No |

The distinction is enforced mechanically. Estimated values remain visible in
the receipt and are counted, but never become success evidence. A release
report must run in `full`, `nightly`, or `release` mode and contain measured
`task_success=1` for every manifest task. A `smoke` report can prove only the
declared smoke subset.

## Smoke gate

The offline PR smoke validates the manifest contract and emits a receipt:

```bash
python tools/benchmark_gate.py smoke --json \
  --output artifacts/benchmark-contract-smoke.json
```

This command executes zero capability tasks. Its `contract_pass` status is
therefore not a measured capability pass, and its `release_ready` value is
always false. To evaluate an actual receipt:

```bash
python tools/benchmark_gate.py smoke \
  --manifest fixtures/bench/capability/capability-manifest.v1.json \
  --report artifacts/smoke-report.json --json
python tools/benchmark_gate.py gate \
  --manifest fixtures/bench/capability/capability-manifest.v1.json \
  --report artifacts/release-report.json --json
```

The runner label must include `platform`, `os`, and `hardware`; this prevents
an unlabeled result from being presented as portable proof.

## Failure artifacts and blocked state

`fail` and `blocked` task results must preserve at least one sanitized failure
artifact. Each artifact has a safe repository-relative path, lowercase
SHA-256, artifact kind, and `sanitized: true`. The allowed kinds are log,
screenshot, video, audio, trace, and document. Missing capability,
permission, and secret are explicit blocked reasons; they are not successes and
must not be silently converted into estimates.

## Current limitations

This commit provides the versioned contract, deterministic validation, and
offline smoke/release decision logic. It does not provide clean-machine
executors for the seven domains, provider A/B execution, dashboard publishing,
nightly scheduling, or measured cross-OS evidence. Those remain follow-up work;
no cross-domain capability claim should be made from the contract smoke.
