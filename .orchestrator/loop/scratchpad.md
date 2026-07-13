---
iteration: 2
max_iterations: 40
completion_promise: "ISSUE-209 TASKENVELOPE DONE"
evidence_required: true
mode: converge
started_at: "2026-07-12T00:00:00Z"
---

Implement GitHub issue #209 (P0 Architecture): a single versioned `TaskEnvelope` and
unified state machine shared by simplicio-agent and simplicio-runtime, so no component
(conversation loop, kernel_binding, runtime run, workflow, simplicio-loop, leases,
GitHub/PR, evidence) can declare success before the whole chain completes.

Canonical states: received → oriented → planned → claimed → executing → validating →
evidence_ready → delivered → closed. Exception states: blocked, cancelled, quarantined,
failed — explicit, idempotent transitions.

Envelope must contain at minimum: schema + schema_version; task_id, parent_id,
correlation_id; repo, branch, scope, write-set; structured acceptance criteria; risk
policy, model, execution policy; current worker/lease; state, attempts, timestamps,
block reason; artifacts, receipts, evidence refs; delivery target (commit/PR/issue/artifact).

Steps:
1. Inventory current state representations: conversation loop, kernel_binding, workflow,
   loop journal, leases, delivery.
2. Define schema `simplicio.task-envelope/v1` + transition contract.
3. Implement types/serialization in the runtime side (this repo, simplicio-agent side;
   coordinate/mirror with simplicio-runtime per the issue's cross-repo note).
4. Implement the corresponding adapter in the agent.
5. Migrate one vertical slice: chat request → run → validate → evidence.
6. Reject invalid/duplicate transitions with a structured error.
7. Persist every transition to a ledger with task_id + envelope hash.
8. Add read-compat for old states without creating a second permanent model.
9. Document ownership: control plane decides state; workers only report events.

Acceptance criteria (all must hold with in-turn evidence before the promise):
- [x] Versioned schema `simplicio.task-envelope/v1` exists and is validated by the runtime.
      MEASURED: agent/task_envelope.py — TaskEnvelope.__post_init__ rejects any
      schema_version != TASK_ENVELOPE_SCHEMA_VERSION; test_wrong_schema_version_is_rejected.
- [ ] Chat, CLI, workflow, and worker all produce the same canonical envelope.
      UNVERIFIED/PENDING: agent/task_envelope_bridge.py + its E2E test now prove ONE
      caller can drive a TaskEnvelope transition and its matching protocol_v1 event
      together (received..closed), but no real conversation_loop/kernel_binding/
      workflow call site constructs a TaskEnvelope yet — still not wired into
      production surfaces. See ADR-0008 "Still open".
- [x] Invalid transitions are rejected deterministically.
      MEASURED: InvalidTransitionError + ALLOWED_TRANSITIONS table;
      test_invalid_transition_is_rejected_deterministically, test_terminal_states_have_no_outgoing_transitions.
- [x] Repeating the same event does not duplicate state or evidence (idempotent).
      MEASURED: same-state transition returns `self`; evidence_refs/receipts/artifacts
      merged via a dedup helper; test_same_state_transition_is_idempotent_noop,
      test_repeated_executing_event_does_not_duplicate_attempts,
      test_repeated_evidence_ref_is_not_duplicated.
- [x] An E2E test walks received → evidence_ready on a real case.
      MEASURED: test_e2e_happy_path_to_closed_with_evidence (goes all the way to closed).
      Still synthetic (no real chat/CLI/workflow driving it) — see the unchecked item above.
- [x] The envelope carries ACs, write-set, lease, and receipts.
      MEASURED: TaskEnvelope fields acceptance_criteria, write_set, lease, receipts + round-trip test.
- [x] The system refuses `closed` without a valid evidence receipt.
      MEASURED: __post_init__ raises ValueError when state is CLOSED and evidence_refs is empty;
      test_closed_refuses_without_evidence_receipt.
- [x] Documentation states explicitly who may change each state.
      MEASURED: docs/architecture/ADR-0008-task-envelope-ownership.md — ownership table
      (control plane / workers / evidence surfaces / delivery surfaces / read-only
      consumers), each row's May-do vs May-NOT-do.
- [ ] `simplicio contracts smoke --json` and focused tests pass.
      MEASURED (focused tests): 35/35 passing —
      `python3 -m pytest tests/agent/test_task_envelope.py tests/agent/test_task_envelope_bridge.py tests/agent/test_protocol_v1.py -q`.
      PENDING: `simplicio contracts smoke` is the external simplicio-runtime CLI, not
      present in this repo/venv — out of this repo's reach alone (documented in
      ADR-0008 cross-repo note); cannot be run or wired from here.

Evidence required: schema diff, transition matrix, E2E test, validation receipt, one real
envelope example. Out of scope: new channels/models/shared-memory transport in this issue.

Iteration 1 evidence (MEASURED): agent/task_envelope.py (new, 370 lines) +
tests/agent/test_task_envelope.py (new, 14 tests, all passing) +
tests/agent/test_protocol_v1.py re-run clean (16 passing, no regression).

Iteration 2 plan: (a) wire the envelope into ONE real vertical slice per step 5
(conversation_loop or the simplicio-loop skill's own task tracking, whichever has the
smallest blast radius), (b) write the ownership doc (step 9), (c) reconcile with
agent/protocol_v1.py per the issue-209 inventory finding — TaskEnvelope transitions
should emit protocol_v1 lifecycle events, not duplicate them, (d) cross-repo mirror
with simplicio-runtime is a separate coordination step, out of this repo's reach alone.

Iteration 2 evidence (MEASURED): agent/task_envelope_bridge.py (new, deterministic
TaskState -> protocol_v1 event_type map + emit_for_transition) + tests/agent/
test_task_envelope_bridge.py (new, 5 tests incl. a received->closed E2E vertical
slice) + docs/architecture/ADR-0008-task-envelope-ownership.md (ownership table +
TaskEnvelope-vs-protocol_v1 reconciliation + cross-repo note). Full focused suite
(test_task_envelope.py + test_task_envelope_bridge.py + test_protocol_v1.py):
35/35 passing, no regressions.

Remaining before the promise can honestly fire: wire a TaskEnvelope into one real
production call site (conversation_loop turn or a `simplicio-loop` iteration's own
tracking — the ORIGINAL Step 5 target, not yet done); this is materially larger
scope (touches conversation_loop.py, thousands of lines) and is deferred to a
follow-up iteration/PR rather than rushed. `simplicio contracts smoke` remains
out of this repo's reach (separate CLI/repo). Given both gaps, this session does
NOT emit the completion promise — the AC "chat/CLI/workflow/worker produce the
same canonical envelope" is still open.

KNOWN GAP (MEASURED, affects every iteration): the simplicio-loop skill's helper
scripts (loop_journal.py, task_anchor.py, watcher_verify.py, task_backlog.py,
impact_audit.py, flow_audit.py, hierarchical_planner.py, cross_agent_wiki.py) are
referenced throughout SKILL.md but do not exist under
~/.claude/skills/simplicio-loop/ (only references/ docs, no scripts/) or anywhere in
this repo. The watcher-gate, stall-detector, and task-anchor mechanics described in
the skill cannot run mechanically. This session substitutes: manual journal.jsonl
appends, manual scratchpad AC checklist edits, and real pytest runs as the promise's
evidence gate. No false "MEASURED" claim is made about a gate that didn't actually run.
