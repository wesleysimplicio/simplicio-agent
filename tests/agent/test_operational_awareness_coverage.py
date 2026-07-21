"""Coverage-raising regression tests for agent.event_store / agent.operational_now.

These target lines the existing focused slice test does not exercise: validation
error paths, corruption/replay recovery, handle-resolution misses, degradation
selection branches, and non-tautological content-hash/round-trip checks.
"""

from __future__ import annotations

import json

import pytest

from agent.belief_state import BeliefAssessment, BeliefDecision, Freshness
from agent.event_store import (
    AwarenessReceipt,
    ExecutionContext,
    OperationalEventStore,
    OperationalEventStoreCorruptError,
    OperationalScope,
    OperationalValueStatus,
    RunEvent,
)
from agent.operational_now import (
    Degradation,
    FieldStatus,
    OperationalField,
    OperationalNowProjector,
    OperationalNowSnapshot,
    OperationalNowStore,
    _select_degradation,
)


COVERAGE_SCOPE = OperationalScope(profile_id="profile-1", tenant_id="tenant-1")


def _receipt(**overrides: object) -> AwarenessReceipt:
    values = dict(
        receipt_id="r1",
        path="goal.anchor",
        value="v",
        status=OperationalValueStatus.CANON,
        freshness=Freshness.FRESH,
        source="operator",
        source_event_id="src-1",
        recorded_at_ns=10,
        payload={"profile_id": "profile-1", "tenant_id": "tenant-1"},
    )
    values.update(overrides)
    return AwarenessReceipt(**values)


# --- event_store.py validation branches -----------------------------------


def test_execution_context_rejects_blank_field():
    with pytest.raises(ValueError, match="profile_id"):
        ExecutionContext(
            profile_id="   ",
            tenant_id="t",
            session_id="s",
            run_id="r",
            goal_hash="g",
            anchor_hash="a",
            phase="p",
            step=0,
        )


def test_execution_context_rejects_negative_step():
    with pytest.raises(ValueError, match="step"):
        ExecutionContext(
            profile_id="p",
            tenant_id="t",
            session_id="s",
            run_id="r",
            goal_hash="g",
            anchor_hash="a",
            phase="p",
            step=-1,
        )


def test_run_event_rejects_blank_causal_parent_and_receipt_hash():
    with pytest.raises(ValueError):
        RunEvent(
            event_id="e1",
            run_id="r1",
            causal_parent="   ",
            sequence=1,
            idempotency_key="k1",
            event_type="t",
            actor="a",
            source="s",
            payload_ref="p",
            classification="c",
        )
    with pytest.raises(ValueError):
        RunEvent(
            event_id="e1",
            run_id="r1",
            causal_parent=None,
            sequence=1,
            idempotency_key="k1",
            event_type="t",
            actor="a",
            source="s",
            payload_ref="p",
            classification="c",
            receipt_hash="   ",
        )


def test_run_event_rejects_unsupported_schema_version():
    with pytest.raises(ValueError, match="schema"):
        RunEvent(
            event_id="e1",
            run_id="r1",
            causal_parent=None,
            sequence=1,
            idempotency_key="k1",
            event_type="t",
            actor="a",
            source="s",
            payload_ref="p",
            classification="c",
            schema_version="bogus/v0",
        )


def test_awareness_receipt_coerces_string_belief_type():
    receipt = _receipt(belief_type="inferred")
    assert receipt.belief_type.value == "inferred"


def test_awareness_receipt_rejects_out_of_range_confidence():
    with pytest.raises(ValueError, match="confidence"):
        _receipt(confidence=1.5)


def test_awareness_receipt_rejects_missing_with_value():
    with pytest.raises(ValueError, match="missing receipts cannot also carry a value"):
        _receipt(missing=True, value="x")


def test_awareness_receipt_rejects_missing_with_distribution():
    with pytest.raises(
        ValueError, match="missing receipts cannot also carry a distribution"
    ):
        _receipt(value=None, missing=True, distribution=(("a", 0.5),))


def test_awareness_receipt_rejects_nonpositive_recorded_at_ns():
    with pytest.raises(ValueError, match="recorded_at_ns"):
        _receipt(recorded_at_ns=0)


def test_awareness_receipt_rejects_nonpositive_optional_time_fields():
    with pytest.raises(ValueError, match="valid_time_ns"):
        _receipt(valid_time_ns=0)


def test_awareness_receipt_content_hash_is_stable_and_sensitive_to_value():
    r1 = _receipt()
    r2 = _receipt()
    assert r1.content_hash() == r2.content_hash()
    r3 = _receipt(value="different")
    assert r3.content_hash() != r1.content_hash()


# --- OperationalEventStore replay/corruption branches ---------------------


def test_iter_receipts_returns_empty_list_when_file_absent(tmp_path):
    store = OperationalEventStore(tmp_path / "missing.jsonl", scope=COVERAGE_SCOPE)
    assert list(store.iter_receipts()) == []


def test_iter_receipts_skips_blank_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    receipt = _receipt()
    path.write_text(
        "\n" + json.dumps(receipt.to_dict()) + "\n\n",
        encoding="utf-8",
    )
    store = OperationalEventStore(path, scope=COVERAGE_SCOPE)
    replayed = list(store.iter_receipts())
    assert replayed == [receipt]


def test_iter_receipts_raises_on_corrupt_json_line(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")
    store = OperationalEventStore(path, scope=COVERAGE_SCOPE)
    with pytest.raises(OperationalEventStoreCorruptError, match="receipt log line 1"):
        list(store.iter_receipts())


def test_iter_receipts_raises_oserror_wrapped_when_path_is_a_directory(tmp_path):
    directory = tmp_path / "events.jsonl"
    directory.mkdir()
    store = OperationalEventStore(directory, scope=COVERAGE_SCOPE)
    with pytest.raises(OperationalEventStoreCorruptError, match="cannot read receipt log"):
        list(store.iter_receipts())


def test_receipt_by_handle_returns_none_when_absent(tmp_path):
    store = OperationalEventStore(tmp_path / "events.jsonl", scope=COVERAGE_SCOPE)
    store.append(_receipt(handle="goal.anchor"))
    assert store.receipt_by_handle("does.not.exist") is None


# --- operational_now.py validation and structural branches ----------------


def test_operational_field_rejects_blank_path():
    with pytest.raises(ValueError, match="path"):
        OperationalField(
            path="  ",
            value=None,
            status=FieldStatus.CANON,
            freshness=Freshness.FRESH,
            source_event_id="e1",
            handle="h1",
        )


def test_operational_field_rejects_missing_with_value():
    with pytest.raises(ValueError, match="missing fields cannot carry a value"):
        OperationalField(
            path="p",
            value="v",
            status=FieldStatus.CANON,
            freshness=Freshness.FRESH,
            source_event_id="e1",
            handle="h1",
            missing=True,
        )


def test_operational_field_content_hash_is_stable_and_sensitive_to_value():
    def make(value: str) -> OperationalField:
        return OperationalField(
            path="p",
            value=value,
            status=FieldStatus.CANON,
            freshness=Freshness.FRESH,
            source_event_id="e1",
            handle="h1",
        )

    a = make("x")
    b = make("x")
    c = make("y")
    assert a.content_hash() == b.content_hash()
    assert a.content_hash() != c.content_hash()


def _empty_snapshot(**overrides: object) -> OperationalNowSnapshot:
    values = dict(
        run_id="run-1",
        profile_id="profile-1",
        tenant_id="tenant-1",
        fields={},
        beliefs={},
        materialized_at_ns=1,
        source_event_count=0,
    )
    values.update(overrides)
    return OperationalNowSnapshot(**values)


def test_snapshot_coerces_string_degradation():
    snapshot = _empty_snapshot(degradation="stale")
    assert snapshot.degradation is Degradation.STALE


def test_snapshot_rejects_mismatched_supplied_hash():
    with pytest.raises(ValueError, match="snapshot_hash does not match"):
        _empty_snapshot(snapshot_hash="deadbeef")


def test_snapshot_resolve_returns_none_when_handle_unmatched():
    snapshot = _empty_snapshot()
    assert snapshot.resolve("nonexistent-handle") is None


def test_snapshot_delta_rejects_non_snapshot_previous():
    snapshot = _empty_snapshot()
    with pytest.raises(TypeError, match="previous must be an OperationalNowSnapshot"):
        snapshot.delta({"not": "a snapshot"})


def test_select_degradation_prioritizes_block_over_everything():
    block = BeliefAssessment(
        subject="belief.x",
        decision=BeliefDecision.BLOCK,
        facts=(),
        conflicts=(),
        missing=(),
        uncertainty=0.9,
        required_observation=None,
        evidence_to_change=(),
    )
    result = _select_degradation(
        field_degradations=[Degradation.CONFLICT], belief_assessments=[block]
    )
    assert result is Degradation.BLOCKED


def test_select_degradation_clarify_yields_conflict():
    clarify = BeliefAssessment(
        subject="belief.x",
        decision=BeliefDecision.CLARIFY,
        facts=(),
        conflicts=(),
        missing=(),
        uncertainty=0.5,
        required_observation=None,
        evidence_to_change=(),
    )
    result = _select_degradation(field_degradations=[], belief_assessments=[clarify])
    assert result is Degradation.CONFLICT


def test_select_degradation_field_stale_when_no_belief_signal():
    result = _select_degradation(
        field_degradations=[Degradation.STALE], belief_assessments=[]
    )
    assert result is Degradation.STALE


def test_projector_marks_stale_and_expired_freshness_as_stale_degradation():
    receipts = [
        _receipt(path="a.field", freshness=Freshness.STALE, recorded_at_ns=1),
        _receipt(
            receipt_id="r2",
            path="b.field",
            freshness=Freshness.EXPIRED,
            recorded_at_ns=2,
            source_event_id="src-2",
        ),
    ]
    snapshot = OperationalNowProjector().project(receipts)
    assert snapshot.fields["a.field"].degradation is Degradation.STALE
    assert snapshot.fields["b.field"].degradation is Degradation.STALE
    assert snapshot.degradation is Degradation.STALE


def test_projector_two_conflicting_receipts_on_same_path_merge_conflict_metadata():
    first = _receipt(
        path="dup.field",
        value="first",
        recorded_at_ns=1,
        source_event_id="src-first",
    )
    second = _receipt(
        path="dup.field",
        value="second",
        recorded_at_ns=2,
        source_event_id="src-second",
    )
    snapshot = OperationalNowProjector().project([first, second])
    field = snapshot.fields["dup.field"]
    assert field.degradation is Degradation.CONFLICT
    assert "src-first" in field.conflicts and "src-second" in field.conflicts
    assert "dup.field" in snapshot.conflicts
    assert snapshot.degradation is Degradation.CONFLICT


def test_snapshot_resolve_matches_belief_by_subject_when_source_event_id_differs():
    receipt = _receipt(
        path="belief.subject_only",
        recorded_at_ns=1,
        confidence=0.9,
        status=OperationalValueStatus.MEASURED,
    )
    snapshot = OperationalNowProjector().project([receipt])
    resolved = snapshot.resolve("belief.subject_only")
    assert resolved is not None
    assert resolved.subject == "belief.subject_only"


def test_projector_marks_unknown_degradation_when_missing_field_present_alone():
    receipts = [
        _receipt(path="present.field", recorded_at_ns=1, source_event_id="src-a"),
        _receipt(
            path="missing.field",
            value=None,
            missing=True,
            freshness=Freshness.UNKNOWN,
            status=OperationalValueStatus.UNKNOWN,
            recorded_at_ns=2,
            source_event_id="src-b",
        ),
    ]
    snapshot = OperationalNowProjector().project(receipts)
    assert snapshot.degradation is Degradation.UNKNOWN


def test_projector_marks_explicit_conflicts_field_degradation():
    receipts = [
        _receipt(path="c.field", conflicts=("other-event",), recorded_at_ns=1),
    ]
    snapshot = OperationalNowProjector().project(receipts)
    assert snapshot.fields["c.field"].degradation is Degradation.CONFLICT
    assert "c.field" in snapshot.conflicts


def test_projector_marks_unknown_degradation_when_only_missing_field_present():
    receipts = [
        _receipt(
            path="d.field",
            value=None,
            missing=True,
            freshness=Freshness.UNKNOWN,
            status=OperationalValueStatus.UNKNOWN,
            recorded_at_ns=1,
        )
    ]
    snapshot = OperationalNowProjector().project(receipts)
    assert snapshot.degradation is Degradation.UNKNOWN


def test_projector_marks_unknown_degradation_when_uncertainty_high():
    receipts = [
        _receipt(
            path="e.field",
            recorded_at_ns=1,
            confidence=0.5,
            status=OperationalValueStatus.MEASURED,
        )
    ]
    receipt = receipts[0]
    # Force high uncertainty without other degrading signals.
    high_uncertainty = AwarenessReceipt(
        receipt_id=receipt.receipt_id,
        path=receipt.path,
        value=receipt.value,
        status=receipt.status,
        freshness=receipt.freshness,
        source=receipt.source,
        source_event_id=receipt.source_event_id,
        recorded_at_ns=receipt.recorded_at_ns,
        uncertainty=0.9,
    )
    snapshot = OperationalNowProjector().project([high_uncertainty])
    assert snapshot.degradation is Degradation.UNKNOWN


def test_projector_belief_with_no_selected_fact_is_absent_from_beliefs():
    receipt = _receipt(
        path="belief.absent",
        value=None,
        missing=True,
        freshness=Freshness.UNKNOWN,
        status=OperationalValueStatus.UNKNOWN,
        recorded_at_ns=1,
        confidence=None,
    )
    snapshot = OperationalNowProjector().project([receipt])
    assert "belief.absent" not in snapshot.beliefs


def test_load_snapshot_reraises_file_not_found(tmp_path):
    store = OperationalNowStore(
        event_log_path=tmp_path / "events.jsonl",
        snapshot_path=tmp_path / "missing_snapshot.json",
        scope=COVERAGE_SCOPE,
    )
    with pytest.raises(FileNotFoundError):
        store.load_snapshot()


def test_load_snapshot_rejects_tampered_hash(tmp_path):
    store = OperationalNowStore(
        event_log_path=tmp_path / "events.jsonl",
        snapshot_path=tmp_path / "snapshot.json",
        scope=COVERAGE_SCOPE,
    )
    store.append(_receipt())
    snapshot = store.project()
    payload = json.loads(store.snapshot_path.read_text(encoding="utf-8"))
    payload["snapshot_hash"] = "0" * 64
    store.snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OperationalEventStoreCorruptError, match="cannot read snapshot"):
        store.load_snapshot()
