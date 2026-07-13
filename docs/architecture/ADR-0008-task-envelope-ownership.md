# ADR-0008: TaskEnvelope/v1 — state ownership

**Status:** Accepted (2026-07-12).
**Owner:** @wesleysimplicio.
**Related:** issue #209 (this ADR), epic #159, `simplicio-runtime#3028`.
**Code:** `agent/task_envelope.py` (schema + state machine + ledger),
`agent/task_envelope_bridge.py` (protocol_v1 event bridge),
`tests/agent/test_task_envelope.py`, `tests/agent/test_task_envelope_bridge.py`.

## Problem

Before `TaskEnvelope`, no single component owned the answer to "is this task
actually done": `agent.conversation_loop` free-form `stored_state`/status
strings, `agent.distributed.protocol.TaskStatus` (an *outcome* enum, not a
lifecycle), `tools.kanban_tools` board statuses, and
`agent.verification_evidence.VerificationEvidence.status` each tracked their
own private notion of progress, and any one of them could report success
before the rest of the chain had actually run.

## Decision: who may change what

`TaskEnvelope` state is **control-plane-owned**; every other surface is a
**worker** that reports events into it and never writes state directly.

| Actor | May do | May NOT do |
|---|---|---|
| **Control plane** (the orchestrating loop/scheduler that owns a `task_id`) | Call `TaskEnvelope.transition(...)`; decide the next allowed state; reject a worker's requested transition; write to the `TaskLedger`. | Skip `ALLOWED_TRANSITIONS`; construct a `CLOSED` envelope without `evidence_refs`. |
| **Workers** (conversation loop turn, `kernel_binding` execution, a runtime run, a workflow agent, a `simplicio-loop` iteration) | Request a transition (e.g. "I finished executing, move to `validating`") by calling into the control plane; attach `artifacts`/`receipts`/`evidence_refs` to the transition they request. | Mutate a `TaskEnvelope` field directly (it is a frozen dataclass — enforced, not just documented); invent a new state string; self-report `closed`. |
| **Evidence/verification surfaces** (`VerificationEvidence`, test runners, the watcher-gate) | Produce the `evidence_refs`/`receipts` a worker attaches when requesting `evidence_ready` or `closed`. | Change `state` themselves — evidence is an input to a transition, never a transition trigger by itself. |
| **Delivery surfaces** (GitHub/PR, commit, artifact store) | Populate `delivery_target` on the `delivered` transition. | Mark a task `closed` on delivery alone — `closed` still requires `evidence_refs` (`__post_init__` raises otherwise). |
| **Read-only consumers** (CLI, gateway, TUI, ACP, dashboards) | Read `TaskEnvelope`/`protocol_v1.Envelope` via `agent.task_envelope_bridge.emit_for_transition`, the `TaskLedger`, or `to_dict()`/`to_json()`. | Write to the envelope or the ledger. |

This mirrors the issue's steps 1 and 9: the control plane decides state,
workers only report events — enforced mechanically by `TaskEnvelope` being
frozen and by `InvalidTransitionError` on any transition outside
`ALLOWED_TRANSITIONS`, not by convention alone.

## `TaskEnvelope` vs. `protocol_v1.Envelope`

They are not competing models. `TaskEnvelope` is the durable *state* of a
task (what a control plane persists and queries); `protocol_v1.Envelope` is
the causal *event stream* about it (what CLI/gateway/TUI/ACP consumers
subscribe to). `agent.task_envelope_bridge.emit_for_transition` is the single
translation point: every committed `TaskEnvelope` transition maps
deterministically (`STATE_TO_EVENT_TYPE`) to exactly one `protocol_v1`
lifecycle/execution event, so a consumer watching the event stream sees the
same lifecycle a `TaskEnvelope` reader would compute from state — no second,
parallel status model.

## Idempotency and duplicate events

Re-requesting the *current* state is a no-op (`TaskEnvelope.transition`
returns `self`, unchanged `attempts`/`updated_at_ns`); `emit_for_transition`
mirrors this and emits nothing for a same-state transition. A worker retrying
a request it already made (e.g. a re-delivered webhook) can never duplicate
state, an evidence ref, or a lifecycle event.

## Cross-repo note

`simplicio-runtime#3028` owns the runtime-side mirror of this schema. This
ADR and `agent/task_envelope.py` are the `simplicio-agent`-side
implementation; the schema id (`simplicio.task-envelope/v1`) and state names
are the wire contract the two repos must keep byte-identical. Reconciling the
two implementations is tracked as follow-up, out of this issue's reach alone
(the issue's "Dependências" section).

## Still open (tracked, not blocking this ADR)

- No real chat/CLI/workflow/worker call site constructs a `TaskEnvelope` yet
  — `agent/task_envelope_bridge.py` and its tests are the smallest possible
  vertical slice (one caller drives an envelope transition and its matching
  protocol event together), not a production integration into
  `agent/conversation_loop.py` or `kernel_binding`. Wiring an actual call site
  is separate follow-up work.
- `simplicio contracts smoke --json` is not yet wired to validate this
  schema.
