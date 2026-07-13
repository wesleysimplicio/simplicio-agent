# Deterministic local benchmark program (issue #23)

This slice defines a versioned benchmark-program contract and a fail-closed
comparison gate. It is intentionally limited to repository-local synthetic
fixtures. It does not run Hermes, OpenClaw, an LLM provider, a real device, or
any network service, and it must not be used as evidence of real capability or
network performance.

## Reproducible setup

From the repository root, use Python 3.13 or the project virtual environment:

```bash
python tools/benchmark_program.py validate-manifest \
  --manifest fixtures/bench/program/benchmark-program-manifest.v1.json

python tools/benchmark_program.py compare \
  --manifest fixtures/bench/program/benchmark-program-manifest.v1.json \
  --baseline fixtures/bench/program/baseline.v1.json \
  --candidate fixtures/bench/program/candidate.v1.json \
  --output artifacts/benchmark-program-gate.json \
  --json
```

The committed baseline and candidate are deterministic receipts over the two
local JSON fixtures. The command exits zero only when every declared stage
metric is valid, the candidate stays within its stage budget, and no metric
regresses beyond its declared tolerance.

Focused verification:

```bash
python -m pytest tests/tools/test_benchmark_program.py
ruff check tools/benchmark_program.py tests/tools/test_benchmark_program.py
```

## v1 contract

`fixtures/bench/program/benchmark-program-manifest.v1.json` declares:

- the `synthetic_fixture` execution mode and disabled network policy;
- ordered local cases and safe repository-relative fixture paths;
- stages with numeric budgets such as `max_duration_ms` and `max_tokens`;
- stage metrics, units, comparison direction, tolerance, and the budget each
  metric consumes.

Each report records a status and numeric metrics for every declared case and
stage. The gate compares baseline and candidate reports deterministically. A
lower-is-better metric regresses when its relative increase exceeds tolerance;
a higher-is-better metric uses the inverse rule; informational metrics are
reported but never create a regression. Any validation error, failed stage,
regression, or budget overrun blocks the gate.

## Explicit limitations

- Fixture values are synthetic and are not wall-clock measurements of Hermes,
  OpenClaw, Simplicio Runtime, or any provider.
- The gate proves only that this versioned local receipt contract behaves as
  specified; it does not prove that an agent can complete any user task.
- No network, credentials, external benchmark corpus, real device, or hosted CI
  result is consumed by this slice.
- Real capability and cross-platform performance require a separate,
  explicitly labeled executor and evidence policy, building on the existing
  [capability release gate](benchmark-release-gate.md) and
  [performance integration manifest](performance-integration.md).
