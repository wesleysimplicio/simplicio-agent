# CI quality gates

Issue #349 adds a small, deterministic merge gate around the checks that can
run without provider credentials. The policy contract lives in
`.github/quality-gates.yml`; `.github/workflows/quality-gates.yml` runs the
required unit, local integration, security, offline cost/latency, coverage,
and Windows diagnostics jobs, then fails its aggregate check when any required
job is not successful.

The coverage contract records the target of 85% global and 90% critical scope
coverage. This bounded slice measures the gate contract suite and keeps the
thresholds reviewable; expanding measurement to the complete product surface
is a separate, baseline-backed change. The cost gate reuses the committed
offline performance baseline and publishes its JSON report as an artifact.

External E2E is deliberately not claimed here: it is marked
`availability: unavailable` and `status: UNVERIFIED` because hosted providers,
credentials, and other external services are not part of this deterministic
workflow. A green quality-gates check therefore proves only the local gates
listed above, never unavailable external E2E.

Branch protection should require the single `quality-gates / All quality gates
pass` check (the aggregate job), in addition to any repository-specific checks.
