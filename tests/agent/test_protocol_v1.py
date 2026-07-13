"""Tests for AgentProtocol/v1 envelope + emitter (issue #225)."""

from __future__ import annotations

import json

import pytest

from agent.protocol_v1 import (
    ControlCommand,
    DuplicateEventError,
    Envelope,
    EventDeduplicator,
    Emitter,
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
