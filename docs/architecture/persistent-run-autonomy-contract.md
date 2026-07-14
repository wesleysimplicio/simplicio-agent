# Persistent run and autonomy contracts (#155, #156)

This slice defines two transport-free value contracts:

- `agent/persistent_run.py` (`simplicio.persistent-run/v1`) owns a resumable
  run lifecycle, deterministic budgets/leases/provider metadata, and an
  idempotent effect journal. Unknown or prepared effects and missing receipts
  fail closed before `completed`.
- `agent/autonomy_policy.py` (`simplicio.autonomy-policy/v1`) owns L0–L4
  profile-scoped decisions, risk classes, action-digest approvals, expiry,
  policy-version binding, and the global killswitch. It never executes an
  action or accepts secrets as persisted provider state.

The modules intentionally do not start workers, call providers, control a
browser/desktop, invoke the Runtime action gate, or alter session/tool
schemas. A caller must record the Runtime/effect receipt and then transition
the immutable value to its next state. The run contract's `content_hash()` is
the persistence/replay anchor; the autonomy policy's decision is an
explanation and authorization input, not proof that an action occurred.

## Verified locally

```text
python -m pytest tests/agent/test_persistent_run.py tests/agent/test_autonomy_policy.py -q
10 passed
python -m ruff check agent/persistent_run.py agent/autonomy_policy.py \
  tests/agent/test_persistent_run.py tests/agent/test_autonomy_policy.py
All checks passed
```

## Explicit limits

`UNVERIFIED|` No clean-machine restart or reboot run, provider cancellation,
cross-surface CLI/Desktop/TUI/gateway wiring, Runtime action-gate/ledger
integration, multi-provider behavior, or cross-OS evidence was executed by
this bounded contract slice. `UNVERIFIED|` No claim is made that #155 or #156
is closed; those claims require the live integration and adversarial/E2E
receipts described by the issues.
