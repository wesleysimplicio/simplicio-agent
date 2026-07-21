# ADR-0020: bounded, acknowledged kernel binding slice for issue #20

- Status: accepted for this slice
- Date: 2026-07-13
- Related: issue #20, ADR-0001, ADR-0003, `tools/kernel_binding.py`

## Decision

Keep the existing agent-owned checkpoint store and harden the thin runtime
boundary instead of replacing `tools/checkpoint_manager.py`:

- `kernel_binding.action_gate.mode` remains config-gated and defaults to
  `required`. A missing, stale, broken, or malformed runtime response blocks a
  flagged-dangerous action. `auto` is an explicit opt-out to the legacy
  approval flow; `off` disables this binding.
- A gate call must return a recognized decision (`allow`, `ask`, `deny`, or a
  block variant). A successful process exit or arbitrary JSON is not a gate
  decision.
- The shadow-git checkpoint remains the rollback source of truth. The optional
  `checkpoint` binding now returns `True` only for an explicit record
  acknowledgement. `checkpoint.mode: required` raises
  `KernelBindingError` when the runtime is unavailable or does not acknowledge
  the record; `checkpoint_manager` continues to keep the real snapshot safe
  and treats the mirror as an additive side note, per ADR-0001.
- Mechanical edit and ledger calls are not expanded into new product behavior.
  Their existing interfaces now also require explicit success markers before
  reporting success (`status`/`applied` for edits, `appended`/`event_id` for
  ledger records). No successful runtime call is inferred from an empty or
  unrelated JSON response.
- Runtime-first native `patch`/`write_file` calls use the same explicit edit
  acknowledgement contract. An empty CLI response, `{}`, or unrelated JSON
  produces an observable capability gap and never claims that a mechanical
  edit was applied; an acknowledged edit emits `savings-event/v1` telemetry.

The shared subprocess client rejects empty stdout. This is intentional: an
empty response cannot prove that a deterministic operation happened.

## Configuration

The existing `config.yaml` shape is the control plane:

```yaml
kernel_binding:
  action_gate:
    mode: required  # required | auto | off
  checkpoint:
    mode: auto      # mirror only; required makes the mirror mandatory
  mechanical_edit:
    mode: required
  ledger:
    mode: auto
```

No new environment variable or user-facing shell shortcut is introduced.

## Measured receipt

Run from the issue-20 worktree on 2026-07-13:

| Check | Result |
|---|---|
| `simplicio --version` | `Simplicio Runtime 3.5.0` |
| `runtime.lock` minimum | `3.5.2` |
| `simplicio gate classify --action 'rm -rf /tmp/x' --json` | real runtime returned `decision: block` |
| `simplicio checkpoint record --json` | real runtime returned `op: list`, not a record acknowledgement |
| `simplicio ledger append --json` | real runtime exited 1: unknown `evidence append` subcommand |
| focused pytest | `85 passed` (`test_kernel_binding.py`, `test_approval_kernel_binding.py`) |
| Ruff | `ruff check` passed for the changed Python files |
| diff validation | `git diff --check` passed |

The local runtime is below the repository pin, so this receipt does not claim
an end-to-end successful checkpoint, mechanical-edit, or ledger operation.

## Gaps and non-goals

- No sibling `simplicio-runtime` checkout was present for a compatible build or
  source-level contract audit.
- The local runtime did not provide a checkpoint-record acknowledgement or a
  ledger-append command, so those paths are covered by explicit negative
  behavior only.
- This slice does not replace the checkpoint manager, add a new MCP/core tool,
  wire `SimplicioBridge` into every caller, or claim full conversation-loop
  integration.
- GitHub issues and remotes were not modified; no push was performed.
