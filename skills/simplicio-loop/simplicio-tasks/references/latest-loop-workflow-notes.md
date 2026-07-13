# Latest loop/workflow notes (2026-07 session)

Concise extracted requirements from the current documented workflow review.

## Background execution
- `simplicio run --background-unit-tests` runs `cargo test --quiet` as a tracked background job.
- Foreground functional gates continue while the background lane runs.
- Commit / push / merge stay blocked until `evidence/background-validation.json` reports `final_gate.status=passed`.
- The background-validation evidence bundle includes the scheduler plan, output lane marker, foreground gate evidence, Cargo lock-wait evidence, and final gate status.

## Parallel execution
- Heavy-path task execution fans out a continuous worker pool for large queues or any medium+ item.
- Autoscale rule: `fleet = min(cap_cpu, cap_mem, cap_disk, items, 16)`.
- Same-file items are serialized; default isolation is one worktree per item.
- Bulk mechanical refactors may use parallel-PR mode with one item per agent and small batches.

## Stop hooks and clean stop
- Armed loops re-feed the goal at turn end via `hooks/loop_stop.py` when the host supports hooks.
- If the host has no hooks, the self-paced fallback handles re-feeding.
- A fresh session is the safe reset if a stop-hook session already ran and stopped.
- `.orchestrator/STOP` is the explicit clean-stop signal.
- Background gates should use `.orchestrator/loop/gate.lock` while a long verification lane is active, then remove it when finished so the stop hook does not re-fire as idle.

## Iteration limits
- Armed body-of-work runs require `.orchestrator/loop/scratchpad.md` with `max_iterations`.
- Backstop rule: `max_iterations = max(10, 3 × item_count)` unless a budget ceiling is explicitly set.
- `0` is only valid when a budget ceiling exists.
- Success requires same-turn evidence with `<promise>SIMPLICIO_DONE</promise>`; a bare promise is ignored.
- The loop must stop at the cap, or earlier only on budget exhaustion or a safety halt.
