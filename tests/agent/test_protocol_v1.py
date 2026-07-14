"""Tests for AgentProtocol/v1 envelope + emitter (issue #225)."""

from __future__ import annotations

import json

import pytest

from agent.protocol_v1 import (
    CausalEventSummary,
    ControlCommand,
    DuplicateEventError,
    Envelope,
    EventClassification,
    EventDeduplicator,
    Emitter,
    ExecutionContext,
    IdempotencyConflictError,
    ImmutableContextError,
    REDACTION_SECRET,
    ReplayCursor,
    RunEvent,
    RunEventStream,
    SecretSafePayload,
    SequenceGapError,
    ExecutionEvent,
    LifecycleEvent,
    PresentationEvent,
    PROTOCOL_VERSION,
    VALID_EVENT_TYPES,
)


# ---------------------------------------------------------------------------
# (a) serialization round-trips with every field present
# ---------------------------------------------------------------------------


def test_envelope_serializes_and_deserializes_all_fields():
    env = Envelope.create(
        event_type=LifecycleEvent.STARTED.value,
        session_id="sess-1",
        session_incarnation=3,
        turn_id="turn-7",
        attempt_id="att-1",
        seq=4,
        payload_version="2.1",
        redaction_class="pii",
        trace_id="trace-abc",
    )

    # Every field must survive a dict round-trip.
    restored = Envelope.from_dict(env.to_dict())
    assert restored == env
    for f in (
        "protocol_version",
        "event_id",
        "session_id",
        "session_incarnation",
        "turn_id",
        "attempt_id",
        "seq",
        "ts_monotonic_ns",
        "ts_wall_ns",
        "event_type",
        "payload_version",
        "redaction_class",
        "trace_id",
    ):
        assert getattr(restored, f) == getattr(env, f), f"field {f} lost"

    # JSON round-trip must be byte-for-byte equivalent on the field set.
    again = Envelope.from_json(env.to_json())
    assert again.to_dict() == env.to_dict()


def test_envelope_json_is_json_parseable_and_complete():
    env = Envelope.create(
        event_type=PresentationEvent.TEXT.value,
        session_id="s",
        turn_id="t",
        attempt_id="a",
        seq=1,
    )
    raw = json.loads(env.to_json())
    assert set(raw.keys()) == {
        "protocol_version",
        "event_id",
        "session_id",
        "session_incarnation",
        "turn_id",
        "attempt_id",
        "seq",
        "ts_monotonic_ns",
        "ts_wall_ns",
        "event_type",
        "payload_version",
        "redaction_class",
        "trace_id",
    }


def test_envelope_defaults_are_populated():
    env = Envelope.create(
        event_type=ExecutionEvent.PROVIDER.value,
        session_id="s",
        turn_id="t",
        attempt_id="a",
        seq=1,
    )
    assert env.protocol_version == PROTOCOL_VERSION
    assert env.event_id  # non-empty uuid hex
    assert env.trace_id
    assert env.seq == 1
    assert env.session_incarnation == 0


# ---------------------------------------------------------------------------
# (b) seq is monotonic per turn_id
# ---------------------------------------------------------------------------


def test_seq_is_monotonic_per_turn_id():
    em = Emitter(session_id="sess", trace_id="trace")
    seqs_turn_a = [
        em.emit(LifecycleEvent.ACCEPTED.value, turn_id="A", attempt_id="1").seq,
        em.emit(PresentationEvent.TEXT.value, turn_id="A", attempt_id="1").seq,
        em.emit(LifecycleEvent.COMPLETED.value, turn_id="A", attempt_id="1").seq,
    ]
    # Strictly increasing and starting at 1 within the turn.
    assert seqs_turn_a == [1, 2, 3]

    # A different turn has its OWN independent sequence.
    seqs_turn_b = [
        em.emit(LifecycleEvent.STARTED.value, turn_id="B", attempt_id="1").seq,
        em.emit(LifecycleEvent.COMPLETED.value, turn_id="B", attempt_id="1").seq,
    ]
    assert seqs_turn_b == [1, 2]

    # Turn A continues independently of turn B.
    seq_a_again = em.emit(
        PresentationEvent.PROGRESS.value, turn_id="A", attempt_id="1"
    ).seq
    assert seq_a_again == 4


def test_seq_is_monotonic_across_attempts_of_same_turn():
    em = Emitter(session_id="s", trace_id="t")
    seqs = []
    for attempt in ("att-1", "att-2", "att-3"):
        # Same turn, new attempt: seq keeps climbing per turn_id.
        env = em.emit(ExecutionEvent.TOOL.value, turn_id="T", attempt_id=attempt)
        seqs.append(env.seq)
    assert seqs == [1, 2, 3]


def test_seq_independent_per_emitter_instance():
    em1 = Emitter(session_id="s", trace_id="t")
    em2 = Emitter(session_id="s", trace_id="t")
    assert em1.emit(ControlCommand.START.value, turn_id="T", attempt_id="a").seq == 1
    # A separate emitter keeps its own counters.
    assert em2.emit(ControlCommand.START.value, turn_id="T", attempt_id="a").seq == 1


# ---------------------------------------------------------------------------
# (c) invalid event_type is rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["lifecycle.bogus", "presentation", "EXECUTION.TOOL", "", "control.nope"]
)
def test_invalid_event_type_rejected_on_create(bad):
    with pytest.raises(ValueError):
        Envelope.create(
            event_type=bad,
            session_id="s",
            turn_id="t",
            attempt_id="a",
            seq=1,
        )


@pytest.mark.parametrize("bad", ["lifecycle.bogus", "control.nope", "random.thing"])
def test_invalid_event_type_rejected_on_from_dict(bad):
    with pytest.raises(ValueError):
        Envelope.from_dict({
            "protocol_version": PROTOCOL_VERSION,
            "event_id": "e",
            "session_id": "s",
            "session_incarnation": 0,
            "turn_id": "t",
            "attempt_id": "a",
            "seq": 1,
            "ts_monotonic_ns": 1,
            "ts_wall_ns": 1,
            "event_type": bad,
            "payload_version": "1.0",
            "redaction_class": "none",
            "trace_id": "tr",
        })


def test_invalid_event_type_rejected_on_emit():
    em = Emitter(session_id="s", trace_id="t")
    with pytest.raises(ValueError):
        em.emit("lifecycle.unknown", turn_id="T", attempt_id="a")


def test_valid_event_types_are_accepted():
    # Sanity: every member of every family is accepted.
    for et in VALID_EVENT_TYPES:
        env = Envelope.create(
            event_type=et,
            session_id="s",
            turn_id="t",
            attempt_id="a",
            seq=1,
        )
        assert env.event_type == et
        assert env.event_family is not None


def _replay_event(event_id: str, *, seq: int = 1) -> Envelope:
    return Envelope.create(
        event_type=LifecycleEvent.STARTED.value,
        event_id=event_id,
        session_id="session",
        turn_id="turn",
        attempt_id="attempt",
        seq=seq,
        ts_monotonic_ns=10,
        ts_wall_ns=20,
    )


def test_event_deduplicator_suppresses_exact_replays():
    event = _replay_event("event-1")
    replayed = Envelope.from_json(event.to_json())
    deduplicator = EventDeduplicator()

    assert deduplicator.accept(event) is True
    assert deduplicator.accept(replayed) is False
    assert len(deduplicator) == 1


def test_event_deduplicator_rejects_event_id_content_collision():
    event = _replay_event("event-1")
    deduplicator = EventDeduplicator()
    deduplicator.accept(event)

    with pytest.raises(DuplicateEventError, match="event-1"):
        deduplicator.accept(_replay_event("event-1", seq=2))


def test_event_deduplicator_replay_preserves_first_seen_order():
    first = _replay_event("event-1")
    second = _replay_event("event-2")
    deduplicator = EventDeduplicator()

    assert deduplicator.replay([first, first, second, second]) == (first, second)
    assert len(deduplicator) == 2


def test_event_deduplicator_replay_is_transactional_on_collision():
    first = _replay_event("event-1")
    conflicting = _replay_event("event-1", seq=2)
    deduplicator = EventDeduplicator()

    with pytest.raises(DuplicateEventError):
        deduplicator.replay([first, conflicting])
    assert len(deduplicator) == 0


def _context(**overrides) -> ExecutionContext:
    data = {
        "profile_id": "profile-1",
        "tenant_id": "tenant-1",
        "session_id": "session-1",
        "run_id": "run-1",
        "parent_run_id": "parent-0",
        "goal_hash": "goal-abc",
        "anchor_hash": "anchor-xyz",
        "phase": "plan",
        "step": "collect",
        "budgets": {"tokens": 10, "seconds": 5},
        "policy_ref": "policy/default",
        "capability_refs": ("cli", "mcp"),
        "checkpoint_ref": "checkpoint/1",
        "effect_journal_ref": "effects/1",
        "ledger_ref": "ledger/1",
        "evidence_coverage": ("tests",),
    }
    data.update(overrides)
    return ExecutionContext(**data)


def _run_event(
    seq: int,
    *,
    context: ExecutionContext | None = None,
    event_id: str | None = None,
    event_type: str = LifecycleEvent.STARTED.value,
    actor: str = "agent",
    source: str = "agent",
    payload: SecretSafePayload | None = None,
    causal_parent: str = "",
    idempotency_key: str = "",
    receipt_hash: str = "",
) -> RunEvent:
    ctx = context or _context()
    env = Envelope.create(
        event_type=event_type,
        event_id=event_id or f"event-{seq}",
        session_id=ctx.session_id,
        turn_id="turn-1",
        attempt_id="attempt-1",
        seq=seq,
        ts_monotonic_ns=10 + seq,
        ts_wall_ns=20 + seq,
    )
    return RunEvent(
        envelope=env,
        context=ctx,
        actor=actor,
        source=source,
        classification=EventClassification.MEASURED.value,
        causal_parent=causal_parent,
        idempotency_key=idempotency_key,
        payload=payload
        or SecretSafePayload.inline({"seq": seq, "kind": event_type}),
        receipt_hash=receipt_hash,
    )


def test_execution_context_canonical_hash_ignores_ordering_noise():
    a = _context(
        budgets={"seconds": 5, "tokens": 10},
        capability_refs=("mcp", "cli"),
        evidence_coverage=("tests", "bench"),
    )
    b = _context(
        budgets={"tokens": 10, "seconds": 5},
        capability_refs=("cli", "mcp"),
        evidence_coverage=("bench", "tests"),
    )

    assert a.to_dict() == b.to_dict()
    assert a.canonical_hash() == b.canonical_hash()


def test_secret_safe_payload_redacts_inline_secret_paths():
    payload = SecretSafePayload.inline(
        {
            "tool": "provider",
            "secret": {"api_key": "super-secret"},
            "nested": [{"token": "abc"}],
        },
        redaction_class=REDACTION_SECRET,
        secret_paths=("secret.api_key", "nested[0].token"),
    )

    encoded = json.dumps(payload.to_dict())
    assert "super-secret" not in encoded
    assert '"[redacted]"' in encoded


def test_run_event_stream_enforces_monotonic_sequences():
    stream = RunEventStream(context=_context())
    stream.append(_run_event(1))

    with pytest.raises(SequenceGapError, match="expected sequence 2, got 3"):
        stream.append(_run_event(3))


def test_run_event_stream_deduplicates_exact_replays():
    stream = RunEventStream(context=_context())
    event = _run_event(1, event_id="event-1")

    assert stream.append(event) is True
    assert stream.append(event) is False
    assert len(stream) == 1


def test_run_event_stream_rejects_idempotency_collision():
    stream = RunEventStream(context=_context())
    stream.append(_run_event(1, idempotency_key="idem-1"))

    with pytest.raises(IdempotencyConflictError, match="idem-1"):
        stream.append(
            _run_event(
                2,
                idempotency_key="idem-1",
                payload=SecretSafePayload.inline({"seq": 2, "kind": "changed"}),
            )
        )


def test_run_event_stream_projection_is_stable_across_replay_duplicates():
    stream_a = RunEventStream(context=_context())
    stream_b = RunEventStream(context=_context())
    first = _run_event(
        1,
        event_type=LifecycleEvent.STARTED.value,
        receipt_hash="receipt-a",
    )
    second = _run_event(
        2,
        event_type=LifecycleEvent.COMPLETED.value,
        receipt_hash="receipt-b",
        causal_parent=first.event_id,
    )

    stream_a.replay([first, first, second])
    stream_b.replay([first, second])

    projection_a = stream_a.project()
    projection_b = stream_b.project()
    assert projection_a.to_dict() == projection_b.to_dict()
    assert projection_a.canonical_hash() == projection_b.canonical_hash()
    assert projection_a.status == "completed"


def test_run_event_stream_cursor_returns_only_unconfirmed_tail():
    stream = RunEventStream(context=_context())
    first = _run_event(1)
    second = _run_event(2, causal_parent=first.event_id)
    stream.replay([first, second])

    assert stream.events_after(ReplayCursor("run-1", 1, first.event_id)) == (second,)


def test_run_event_stream_coarse_graining_is_bounded_causal_and_reversible():
    stream = RunEventStream(context=_context())
    events = []
    causal_parent = "external-trigger"
    for sequence in range(1, 65):
        event = _run_event(
            sequence,
            causal_parent=causal_parent,
            payload=SecretSafePayload.inline({"blob": "x" * 4096, "seq": sequence}),
        )
        stream.append(event)
        events.append(event)
        causal_parent = event.event_id

    summary = stream.coarse_grain(max_context_bytes=1024)
    encoded = json.dumps(summary.to_dict(), sort_keys=True, separators=(",", ":"))
    restored = CausalEventSummary.from_dict(json.loads(encoded))

    assert len(encoded.encode("utf-8")) <= 1024
    assert "blob" not in encoded
    assert summary.event_count == len(events)
    assert summary.causal_parent == "external-trigger"
    assert summary.first_event_id == events[0].event_id
    assert summary.last_event_id == events[-1].event_id
    assert stream.expand_causal_summary(restored) == tuple(events)
    assert [event.causal_parent for event in stream.expand_causal_summary(restored)] == [
        "external-trigger",
        *(event.event_id for event in events[:-1]),
    ]

    with pytest.raises(ValueError, match="exceeds context budget"):
        stream.coarse_grain(max_context_bytes=summary.context_size_bytes - 1)

    tampered = summary.to_dict()
    tampered["causal_digest"] = "0" * 64
    with pytest.raises(ValueError, match="does not match the event stream"):
        stream.expand_causal_summary(CausalEventSummary.from_dict(tampered))


def test_run_event_stream_rejects_tool_goal_hash_mutation():
    stream = RunEventStream(context=_context())

    with pytest.raises(ImmutableContextError, match="goal_hash"):
        stream.append(
            _run_event(
                1,
                source="tool",
                event_type=ExecutionEvent.TOOL.value,
                context=_context(goal_hash="goal-other"),
            )
        )
