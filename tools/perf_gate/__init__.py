"""CI performance-regression gate (issue #116).

Runs the existing offline benchmark harness (``scripts/benchmark_e2e.py
--json``) N times, aggregates a median ``per_op_us`` per (scenario, variant)
pair, and compares it against a committed CI baseline
(``tools/perf_gate/baseline_ci.json``). A regression beyond the documented
threshold fails the gate.

See ``docs/performance.md`` (section "CI performance-regression gate") for
the full contract, and ``tools/rename_guard/`` for the sibling
baseline+bootstrap pattern this module follows.
"""
