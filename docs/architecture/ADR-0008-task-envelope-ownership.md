# ADR-0008: TaskEnvelope/v1 — state ownership

**Status:** Accepted (2026-07-12).
**Owner:** @wesleysimplicio.
**Related:** issue #209 (this ADR), epic #159, `simplicio-runtime#3028`.
**Code:** `agent/task_envelope.py` (schema + state machine + ledger),
`agent/task_envelope_bridge.py` (protocol_v1 event bridge),
`agent/turn_envelope.py` (chat-turn wiring),
`tests/agent/test_task_envelope.py`, `tests/agent/test_task_envelope_bridge.py`,
`tests/agent/test_turn_envelope.py`.

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

The bridge also fails closed for forged snapshots: an event is emitted only
for a state pair present in `ALLOWED_TRANSITIONS`, with the same task lineage
(`task_id`, correlation, repository/scope, acceptance criteria, and creation
timestamp). A same-state replay whose metadata differs from the prior
envelope is rejected rather than treated as an idempotent no-op. This keeps
the protocol event stream owned by the control plane instead of allowing a
worker to manufacture a later state by constructing a replacement dataclass.
Transition receipts, evidence references, and artifacts are append-only;
attempt counts and update timestamps are monotonic as well. Empty or duplicate
receipt/evidence/artifact references, blocked envelopes without a reason, and
backdated transitions are rejected at the envelope boundary.

## Cross-repo note

`simplicio-runtime#3028` owns the runtime-side mirror of this schema. This
ADR and `agent/task_envelope.py` are the `simplicio-agent`-side
implementation; the schema id (`simplicio.task-envelope/v1`) and state names
are the wire contract the two repos must keep byte-identical. Reconciling the
two implementations is tracked as follow-up, out of this issue's reach alone
(the issue's "Dependências" section).

## Still open (tracked, not blocking this ADR)

- **Partially closed.** `agent/turn_envelope.py` now wires one real
  production call site: `agent.conversation_loop.run_conversation`
  constructs a `TaskEnvelope` per chat turn (`start_turn_envelope`, fast-
  forwarded to `executing`) and `agent.turn_finalizer.finalize_turn` drives
  it to its real terminal state (`closed`/`failed`/`blocked`) via
  `finish_turn_envelope`, using the exact `completed`/`failed`/`interrupted`
  outcome `finalize_turn` already computes — no second status model is
  invented. See `tests/agent/test_turn_envelope.py` for the end-to-end
  (non-synthetic) exercise of this path.
  - The chat wiring appends the initial `received` envelope and every
    committed transition to the per-agent `TaskLedger`, and retains the
    matching `protocol_v1` event trail for read-only consumers. Repeated start
    or finalization calls for the same turn are idempotent.
  - This covers only the **chat** surface, and only the default
    (non-`codex_app_server`) transport within it — the `codex_app_server`
    bypass in `run_conversation` still returns before an envelope is ever
    started, which is a documented, deliberate gap (that subprocess-backed
    transport has its own turn shape and needs its own integration, not a
    forced fit into this one).
  - **CLI, workflow, and worker surfaces still do not construct a
    `TaskEnvelope`** — the AC "Chat, CLI, workflow and worker produce the
    same canonical envelope" is *not* fully satisfied. `kernel_binding`,
    the runtime `run` path, workflow dispatch, and `simplicio-loop`
    iterations each still track their own ad-hoc status. Wiring those is
  separate follow-up work, one surface at a time, following the same
  smallest-blast-radius pattern used here.
- `simplicio contracts smoke --json` is not yet wired to validate this
  schema.
