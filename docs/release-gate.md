# Release Gate

`tools/release_gate.py` is the bounded issue `#195` slice for the rename and release gate.
It defines a machine-readable `release-matrix/v1`, deterministic case expansion, artifact and
environment evidence records, rollback evidence schema, and fail-closed required-tier promotion
evaluation.

This slice does **not** execute clean-machine installs, upgrades, or rollbacks. It does **not**
claim that the end-to-end release gate is already satisfied. The goal here is narrower:

- freeze the matrix contract in JSON;
- generate stable case IDs for CI and evidence bundles;
- require digest-pinned artifacts and environment manifests in every evidence record;
- require rollback evidence for rollback scenarios; and
- block stable promotion whenever any required-tier case is missing, invalid, or non-passing.

## Schemas

- Matrix: `simplicio.release-matrix/v1`
- Expanded matrix: `simplicio.release-matrix-expanded/v1`
- Evidence bundle: `simplicio.release-evidence/v1`
- Rollback evidence: `simplicio.release-rollback-evidence/v1`
- Evaluation report: `simplicio.release-gate-report/v1`

## Matrix model

The committed fixture lives under [fixtures/release-matrix](/C:/Users/Z0059V7A/orca/workspaces/simplicio-agent/wave2-195-release-gate/fixtures/release-matrix).
The seed document keeps the issue dimensions explicit:

- `os`
- `channel`
- `scenario`
- `state`
- `aliases`
- `runtime`
- `fast_stack`
- `locale`

Each axis value is tagged as `required` or `experimental`. Expansion is deterministic:

1. axes keep document order;
2. values keep document order inside each axis;
3. excluded combinations are removed by exact `when` match;
4. case IDs are joined as `axis=value__axis=value`;
5. a case is `required` only when every selected axis value is `required`.

That makes the required-tier surface explicit and audit-friendly without pretending that the full
clean-machine harness already exists.

## Evidence model

Every evidence record is tied to one expanded case ID and must include:

- artifact identity with `sha256:` digest;
- environment descriptor with canonical manifest digest;
- receipts list;
- rollback evidence when `scenario=rollback`.

The evaluator is intentionally fail-closed for stable promotion:

- missing required case -> block;
- invalid evidence bundle -> block;
- required case with `fail`, `blocked`, or `skipped` -> block;
- experimental cases are reported but do not, by themselves, promote or block stable.

## CLI

```bash
python tools/release_gate.py expand fixtures/release-matrix/release-matrix.v1.json
python tools/release_gate.py validate-matrix fixtures/release-matrix/release-matrix.v1.json
python tools/release_gate.py validate-evidence \
  fixtures/release-matrix/release-matrix.v1.json \
  fixtures/release-matrix/release-evidence.v1.json
python tools/release_gate.py evaluate \
  fixtures/release-matrix/release-matrix.v1.json \
  fixtures/release-matrix/release-evidence.v1.json
```

The CLI is intended for fixture validation and CI wiring. It is not a substitute for the later
clean-machine and artifact-execution work still required by issue `#195`.
