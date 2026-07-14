"""Focused regression tests for the bounded operational-awareness slice."""

from __future__ import annotations

import json
from pathlib import Path

from agent.belief_state import (
    BeliefDecision,
    BeliefObservation,
    BeliefStateEngine,
    BeliefType,
    Freshness,
    SourceReliability,
)
from agent.event_store import AwarenessReceipt, OperationalEventStore
from agent.operational_now import (
    Degradation,
    FieldStatus,
    OperationalNowProjector,
    OperationalNowStore,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "operational_awareness"


def load_receipts(name: str = "replay_v1.jsonl") -> list[AwarenessReceipt]:
    return [
        AwarenessReceipt.from_dict(json.loads(line))
        for line in (FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_event_store_round_trip_preserves_receipts_and_handle_lookup(tmp_path):
    store = OperationalEventStore(tmp_path / "awareness.jsonl")
    receipts = load_receipts()

    for receipt in receipts:
        store.append(receipt)

    replayed = list(store.iter_receipts())
    assert replayed == receipts
    assert store.receipt_by_handle("goal.anchor") == receipts[0]


def test_operational_now_projection_is_deterministic_and_explicit_about_state():
    projector = OperationalNowProjector(
        source_reliability={
            "filesystem": SourceReliability("filesystem", "1", 1.0),
            "screenshot": SourceReliability("screenshot", "1", 0.7),
            "planner": SourceReliability("planner", "1", 0.9),
            "operator": SourceReliability("operator", "1", 1.0),
            "governor": SourceReliability("governor", "1", 0.95),
            "reconciler": SourceReliability("reconciler", "1", 0.5),
        }
    )
    receipts = load_receipts()

    snapshot = projector.project(receipts)
    replay = projector.project(list(reversed(list(reversed(receipts)))))

    assert snapshot == replay
    assert snapshot.snapshot_hash == replay.snapshot_hash
    assert snapshot.degradation is Degradation.CONFLICT
    assert snapshot.conflicts == ("belief.world_state",)
    assert snapshot.fields["goal.anchor"].status is FieldStatus.CANON
    assert snapshot.fields["run.phase"].status is FieldStatus.MEASURED
    assert snapshot.fields["attention.target"].status is FieldStatus.INFERRED
    assert snapshot.fields["budget.tokens"].status is FieldStatus.PLANNED
    assert snapshot.fields["open_loops.count"].missing is True
    assert snapshot.fields["open_loops.count"].status is FieldStatus.UNKNOWN
    assert snapshot.beliefs["belief.world_state"].freshness is Freshness.FRESH
    assert snapshot.beliefs["belief.world_state"].conflicts == (
        "belief.world_state:source-belief-2",
    )
    assert snapshot.resolve("goal.anchor").value == "keep awareness bounded"


def test_belief_engine_marks_conflict_staleness_and_missing_state_explicitly():
    engine = BeliefStateEngine(
        source_reliability={
            "filesystem": SourceReliability("filesystem", "1", 1.0),
            "screenshot": SourceReliability("screenshot", "1", 0.7),
        }
    )
    conflicting = engine.fuse(
        [
            BeliefObservation(
                subject="belief.world_state",
                source="filesystem",
                source_event_id="event-fresh",
                value={"workspace": "dirty"},
                belief_type=BeliefType.OBSERVED,
                freshness=Freshness.FRESH,
                confidence=0.9,
            ),
            BeliefObservation(
                subject="belief.world_state",
                source="screenshot",
                source_event_id="event-stale",
                value={"workspace": "clean"},
                belief_type=BeliefType.OBSERVED,
                freshness=Freshness.STALE,
                confidence=0.6,
            ),
        ],
        subject="belief.world_state",
        require_fresh=True,
    )
    assert conflicting.decision is BeliefDecision.BLOCK
    assert conflicting.conflicts == ("belief.world_state:event-stale",)
    assert conflicting.required_observation == "belief.world_state"
    assert conflicting.evidence_to_change == ("event-stale",)

    missing = engine.fuse(
        [
            BeliefObservation(
                subject="belief.approval",
                source="reconciler",
                source_event_id="event-missing",
                missing=True,
                freshness=Freshness.UNKNOWN,
            )
        ],
        subject="belief.approval",
    )
    assert missing.decision is BeliefDecision.DEFER
    assert missing.selected_fact is None
    assert missing.missing == ("belief.approval",)
    assert missing.required_observation == "belief.approval"


def test_snapshot_rebuilds_when_persisted_snapshot_is_corrupt(tmp_path):
    event_log = tmp_path / "events.jsonl"
    snapshot_path = tmp_path / "snapshot.json"
    store = OperationalNowStore(event_log_path=event_log, snapshot_path=snapshot_path)

    for receipt in load_receipts():
        store.append(receipt)
    rebuilt = store.project()

    snapshot_path.write_text("{not-json}", encoding="utf-8")
    recovered = store.load_or_rebuild()

    assert recovered == rebuilt
    assert recovered.snapshot_hash == rebuilt.snapshot_hash
    assert (
        json.loads(snapshot_path.read_text(encoding="utf-8"))["snapshot_hash"]
        == rebuilt.snapshot_hash
    )
