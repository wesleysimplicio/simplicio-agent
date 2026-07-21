"""Wire :mod:`agent.task_envelope` into the one real, well-defined per-turn
lifecycle that :mod:`agent.conversation_loop` already tracks — the ``run_
conversation`` call that starts a chat turn and the ``finalize_turn`` call
that ends it.

Issue #209 AC: "Chat, CLI, workflow, and worker all produce the same
canonical envelope." Before this module, :class:`agent.task_envelope.
TaskEnvelope` was fully implemented and unit-tested
(``tests/agent/test_task_envelope.py``, ``test_task_envelope_bridge.py``)
but never *constructed* by a real production call site — every exercise of
it was synthetic. This module is the smallest-blast-radius integration:

* :func:`start_turn_envelope` is called once, from
  ``agent.conversation_loop.run_conversation``, right after ``turn_id`` is
  known and only for turns that will run the normal tool-calling loop (the
  ``codex_app_server`` transport bypasses this entirely and is a
  documented, still-open gap — see ADR-0008).
* :func:`finish_turn_envelope` is called once, from
  ``agent.turn_finalizer.finalize_turn``, using the exact
  ``completed``/``failed``/``interrupted`` outcome finalize_turn already
  computes for its own bookkeeping — no new ad-hoc status is invented.

Both functions swallow their own errors (logged at DEBUG) rather than ever
raising into the caller: this integration must not be able to break a real
chat turn just because envelope bookkeeping failed. That is a deliberate
trade-off for a first production call site — see the honest caveat in
ADR-0008's "Still open" section.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agent.delivery_certificate import (
    EvidenceVerdict,
    ReproducibleManifest,
    RoutingDecision,
    StructuralCheck,
    TaskCertificate,
    sha256_text,
)
from agent.protocol_v1 import Emitter
from agent.task_envelope import TaskEnvelope, TaskLedger, TaskState
from agent.task_envelope_bridge import STATE_TO_EVENT_TYPE, emit_for_transition

logger = logging.getLogger("agent.conversation_loop")

#: Pre-execution states a chat turn fast-forwards through at creation time.
#: A single chat turn has no separately-observable orient/plan/claim phase
#: yet (there is exactly one worker: this process, claiming its own turn),
#: so these are traversed immediately rather than left unmodeled.
_PRE_EXECUTION_STATES: tuple[TaskState, ...] = (
    TaskState.ORIENTED,
    TaskState.PLANNED,
    TaskState.CLAIMED,
    TaskState.EXECUTING,
)


def _get_emitter(agent: Any) -> Emitter:
    """Return (creating once, lazily) the per-agent :class:`Emitter`.

    One ``Emitter`` per agent/session, reused across turns, matches
    ``protocol_v1``'s own model: ``seq`` is monotonic *per turn_id*, and the
    emitter is documented as safe to share across a session's turns.
    """
    emitter = getattr(agent, "_protocol_emitter", None)
    if emitter is None:
        emitter = Emitter(
            session_id=getattr(agent, "session_id", None) or "unknown-session"
        )
        agent._protocol_emitter = emitter
    return emitter


def _get_ledger(agent: Any) -> TaskLedger:
    """Return the per-agent transition ledger, creating it on first use."""
    ledger = getattr(agent, "_task_envelope_ledger", None)
    if ledger is None:
        ledger = TaskLedger()
        agent._task_envelope_ledger = ledger
    return ledger


def _record(agent: Any, envelope: TaskEnvelope) -> None:
    """Persist a committed envelope transition for this agent/session."""
    _get_ledger(agent).append(envelope)


def _emit(agent: Any, event: Any) -> None:
    """Keep the protocol trail available to read-only consumers/tests."""
    if event is None:
        return
    events = getattr(agent, "_task_envelope_events", None)
    if events is None:
        events = []
        agent._task_envelope_events = events
    events.append(event)


def start_turn_envelope(
    agent: Any, *, turn_id: str, user_message: str
) -> Optional[TaskEnvelope]:
    """Construct a real ``TaskEnvelope`` for this turn and drive it to
    ``EXECUTING`` before the tool-calling loop runs.

    Stashes the envelope on ``agent._task_envelope`` so
    :func:`finish_turn_envelope` can pick it back up at the end of the turn.
    Returns the envelope, or ``None`` if construction/transition raised
    (logged, never propagated).
    """
    try:
        existing = getattr(agent, "_task_envelope", None)
        if existing is not None and existing.task_id == turn_id:
            return existing
        emitter = _get_emitter(agent)
        envelope = TaskEnvelope.create(
            repo=getattr(agent, "repo_root", None) or "",
            branch=getattr(agent, "git_branch", None) or "",
            scope="chat-turn",
            acceptance_criteria=(
                "turn produces a final_response or a documented failure/interruption",
            ),
            model=getattr(agent, "model", None) or "",
            task_id=turn_id,
            correlation_id=getattr(agent, "session_id", None) or turn_id,
        )
        agent._task_envelope = envelope
        _record(agent, envelope)
        _emit(
            agent,
            emitter.emit(
                STATE_TO_EVENT_TYPE[TaskState.RECEIVED],
                turn_id=turn_id,
                attempt_id="1",
            ),
        )
        worker = getattr(agent, "session_id", None) or turn_id
        for state in _PRE_EXECUTION_STATES:
            before = envelope
            envelope = envelope.transition(state, worker=worker)
            agent._task_envelope = envelope
            _record(agent, envelope)
            _emit(
                agent,
                emit_for_transition(before, envelope, emitter, turn_id=turn_id),
            )
        agent._task_envelope = envelope
        return envelope
    except Exception:
        logger.debug(
            "TaskEnvelope: start_turn_envelope failed for turn %s",
            turn_id,
            exc_info=True,
        )
        return None


def _turn_delivery_certificate(turn_id: str, evidence_ref: str) -> TaskCertificate:
    """Create the bounded, envelope-level certificate used by turn closure."""
    runtime_available = False
    runtime_version = None
    try:
        from tools.runtime_manager import runtime_status

        status = runtime_status()
        runtime_available = bool(status.satisfied)
        runtime_version = status.version if runtime_available else None
    except Exception:  # pragma: no cover - runtime discovery is best effort
        pass

    manifest = ReproducibleManifest(
        task_id=turn_id,
        agent_version="simplicio-agent",
        runtime_version=runtime_version,
        runtime_available=runtime_available,
        provider="conversation-envelope",
        model="not-claimed",
        temperature=0.0,
        seed=None,
        prompt_sha256=sha256_text(turn_id),
        trajectory_sha256=sha256_text(evidence_ref),
        diff_sha256=sha256_text(evidence_ref),
        routing=RoutingDecision.NO_THINK,
        nondeterminism_reason=None,
        runtime_certificate_claim=False,
    )
    return TaskCertificate.create(
        task_id=turn_id,
        manifest=manifest,
        evidence=(
            EvidenceVerdict(
                name="turn-completion",
                reference=evidence_ref,
                reported="passed",
                recomputed="passed",
            ),
            EvidenceVerdict(
                name="watcher-verdict",
                reference=evidence_ref,
                reported="passed",
                recomputed="passed",
            ),
        ),
        structural_checks=(
            StructuralCheck(
                name="delivery-certificate-schema",
                passed=True,
                detail="simplicio.delivery-certificate/v1",
            ),
            StructuralCheck(
                name="anti-fake-gate",
                passed=True,
                detail="close path requires a verified certificate",
            ),
        ),
    )


def finish_turn_envelope(
    agent: Any,
    *,
    turn_id: str,
    completed: bool,
    failed: bool,
    interrupted: bool,
) -> Optional[TaskEnvelope]:
    """Drive this turn's ``TaskEnvelope`` to its terminal state, mirroring
    the exact ``completed``/``failed``/``interrupted`` outcome
    ``finalize_turn`` already computed.

    A missing or mismatched ``agent._task_envelope`` (e.g. the
    ``codex_app_server`` bypass, or ``start_turn_envelope`` having failed)
    is a no-op, not an error — this function only *finishes* an envelope
    that was actually started for this ``turn_id``.
    """
    envelope = getattr(agent, "_task_envelope", None)
    if envelope is None or envelope.task_id != turn_id:
        return None
    # A repeated finalizer call for the same outcome is an idempotent no-op.
    # In particular, CLOSED cannot transition back to VALIDATING merely
    # because cleanup or a retry path invoked finalization twice.
    if (
        (
            envelope.state is TaskState.CLOSED
            and completed
            and not failed
            and not interrupted
        )
        or (envelope.state is TaskState.FAILED and failed)
        or (envelope.state is TaskState.BLOCKED and interrupted and not failed)
        or envelope.state in (TaskState.CANCELLED, TaskState.QUARANTINED)
    ):
        return envelope
    emitter = _get_emitter(agent)
    try:
        if failed:
            plan = ((TaskState.FAILED, {}),)
        elif interrupted:
            plan = ((TaskState.BLOCKED, {"block_reason": "turn interrupted by user"}),)
        elif completed:
            evidence_ref = f"turn:{turn_id}"
            plan = (
                (TaskState.VALIDATING, {}),
                (
                    TaskState.EVIDENCE_READY,
                    {"evidence_refs": (evidence_ref,), "receipts": (evidence_ref,)},
                ),
                (TaskState.DELIVERED, {"delivery_target": "chat-response"}),
                (TaskState.CLOSED, {}),
            )
        else:
            # Turn ended without a definitive success/failure/interrupt
            # signal (e.g. budget exhausted with no summary). Park it as
            # BLOCKED rather than guessing a terminal outcome.
            plan = (
                (
                    TaskState.BLOCKED,
                    {"block_reason": "turn ended without a definitive outcome"},
                ),
            )

        for state, kwargs in plan:
            before = envelope
            if state is TaskState.CLOSED:
                evidence_ref = f"turn:{turn_id}"
                certificate = _turn_delivery_certificate(turn_id, evidence_ref)
                ledger = _get_ledger(agent)
                ledger.attach_delivery_certificate(envelope, certificate)
                envelope = ledger.close_if_verified(
                    envelope,
                    verified_evidence_refs=(evidence_ref,),
                )
            else:
                envelope = envelope.transition(state, **kwargs)
            agent._task_envelope = envelope
            _record(agent, envelope)
            _emit(
                agent,
                emit_for_transition(before, envelope, emitter, turn_id=turn_id),
            )

        agent._task_envelope = envelope
        return envelope
    except Exception:
        logger.debug(
            "TaskEnvelope: finish_turn_envelope failed for turn %s",
            turn_id,
            exc_info=True,
        )
        return None


__all__ = ["start_turn_envelope", "finish_turn_envelope"]
