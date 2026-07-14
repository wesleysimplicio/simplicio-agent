# Quarantine ledger close gate (#252)

Issue #252 is the tracking record for the 116 broad issues that must remain
open until each one has reproducible defect acceptance criteria and an
independent delivery receipt. The merged ledger work records denied close
attempts, but the issue-repro probe is also a close boundary: a command that
returns zero is not sufficient evidence for closing an enhancement, epic,
roadmap, or other item without a concrete defect signal.

The probe now emits a `close_gate` receipt for every result. A result is
`closeable` only when all of these are true:

1. the issue has a `bug`, `regression`, `defect`, or `assert` label;
2. the probed command is the exact command tied to a reported failure or
   reproduction section, rather than a command merely mentioned in the body;
3. the command exits with `rc=0` without timing out; and
4. merged delivery evidence and an independent evidence receipt are present.

Any missing condition is `quarantined` with a reason. The probe never closes an
issue; callers must preserve the quarantine receipt and perform a separate
live re-query before any close operation.

`tests/test_issue_repro_probe.py` covers the label, exact-command,
delivery/evidence, and passing-repro gates. The live #252 state remains open by
policy: its ledger PR is merged, while the 116 tracked items still lack
individual acceptance criteria and delivery evidence.
