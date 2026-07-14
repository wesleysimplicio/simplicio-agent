"""Focused tests for issue #139's bounded operational self-model contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.operational_self_model import (
    EvidenceLink,
    Freshness,
    MemoryRecord,
    OperationalSelfModel,
    OperationalSelfModelError,
    PromotionStatus,
    SelfModelView,
    Sensitivity,
    TemporalInterval,
)


UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _record(
    record_id: str = "r-1",
    *,
    valid_start: datetime = BASE,
    recorded_start: datetime = BASE,
    expires_at: datetime = BASE + timedelta(days=30),
    evidence_verified: bool = True,
    profile: str = "default",
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
    value: object = "healthy",
    **overrides: object,
) -> MemoryRecord:
    fields: dict[str, object] = {
        "record_id": record_id,
        "subject": "agent",
        "predicate": "capability.state",
        "value": value,
        "valid_time": TemporalInterval(valid_start),
        "recorded_time": TemporalInterval(recorded_start),
        "provenance": (
            EvidenceLink("e-" + record_id, "receipt", "receipt://" + record_id, evidence_verified),
        ),
        "confidence": 0.9,
        "freshness": Freshness(recorded_start, expires_at),
        "profile": profile,
        "sensitivity": sensitivity,
        "view": SelfModelView.CAPABILITY,
    }
    fields.update(overrides)
    return MemoryRecord(
        **fields,
    )


def test_bitemporal_query_reproduces_historical_knowledge() -> None:
    model = OperationalSelfModel()
    model.append(_record("old", value="degraded", recorded_start=BASE))
    model.supersede("old", _record("new", value="healthy", recorded_start=BASE + timedelta(days=2)))

    historical = model.query(
        valid_at=BASE + timedelta(days=1),
        recorded_at=BASE + timedelta(days=1),
        view=SelfModelView.CAPABILITY,
    )
    current = model.query(
        valid_at=BASE + timedelta(days=3),
        recorded_at=BASE + timedelta(days=3),
        view=SelfModelView.CAPABILITY,
    )
    assert [record.value for record in historical] == ["degraded"]
    assert [record.value for record in current] == ["healthy"]


def test_confidence_and_evidence_are_part_of_verified_contract() -> None:
    model = OperationalSelfModel()
    record = _record("evidence")
    model.append(record)

    result = model.verify("evidence", now=BASE + timedelta(days=1))
    assert result.verified is True
    assert record.confidence == 0.9
    assert record.evidence[0].reference == "receipt://evidence"

    with pytest.raises(OperationalSelfModelError, match="confidence"):
        _record("bad-confidence", confidence=1.1)


def test_freshness_and_missing_or_failed_evidence_fail_closed() -> None:
    model = OperationalSelfModel()
    model.append(_record("stale", expires_at=BASE + timedelta(hours=1)))
    model.append(_record("unverified", evidence_verified=False))
    model.append(_record("checker", evidence_verified=True))

    assert not model.verify("stale", now=BASE + timedelta(hours=2)).verified
    assert not model.verify("unverified", now=BASE + timedelta(hours=1)).verified

    checked = OperationalSelfModel(evidence_checker=lambda _link: False)
    checked.append(_record("checker"))
    result = checked.verify("checker", now=BASE + timedelta(hours=1))
    assert result.verified is False
    assert "unverified evidence: e-checker" in result.gaps
    assert checked.query(valid_at=BASE + timedelta(hours=1), recorded_at=BASE + timedelta(hours=1)) == ()


def test_invalid_temporal_provenance_and_profile_fields_are_rejected() -> None:
    with pytest.raises(OperationalSelfModelError, match="timezone-aware"):
        TemporalInterval(datetime(2026, 1, 1))
    with pytest.raises(OperationalSelfModelError, match="provenance"):
        MemoryRecord(
            "no-evidence",
            "agent",
            "predicate",
            True,
            TemporalInterval(BASE),
            TemporalInterval(BASE),
            (),
            0.5,
            Freshness(BASE, BASE + timedelta(days=1)),
        )
    with pytest.raises(OperationalSelfModelError, match="profile"):
        _record("bad-profile", profile="")


def test_bound_is_hard_and_query_is_bounded() -> None:
    model = OperationalSelfModel(max_records=2, max_view_records=1)
    model.append(_record("one"))
    model.append(_record("two"))
    with pytest.raises(OperationalSelfModelError, match="bound"):
        model.append(_record("three"))
    with pytest.raises(OperationalSelfModelError, match="limit"):
        model.query(limit=2)


def test_supersede_and_contradict_preserve_versions() -> None:
    model = OperationalSelfModel()
    model.append(_record("base"))
    model.supersede("base", _record("replacement", value="healthy", recorded_start=BASE + timedelta(days=1)))
    model.contradict("base", _record("contradiction", value="unknown", recorded_start=BASE + timedelta(days=1)))

    assert {record.record_id for record in model.records} == {"base", "replacement", "contradiction"}
    active = model.query(valid_at=BASE + timedelta(days=2), recorded_at=BASE + timedelta(days=2))
    assert {record.record_id for record in active} == {"replacement", "contradiction"}
    versions = model.query(
        valid_at=BASE + timedelta(days=2), recorded_at=BASE + timedelta(days=2), include_versions=True
    )
    assert {record.record_id for record in versions} == {"base", "replacement", "contradiction"}


def test_profile_and_sensitive_memory_are_isolated_in_snapshot() -> None:
    model = OperationalSelfModel()
    model.append(_record("default", profile="default"))
    model.append(_record("other", profile="other"))
    model.append(_record("secret", sensitivity=Sensitivity.SENSITIVE))

    snapshot = model.snapshot("incarnation-1", valid_at=BASE + timedelta(days=1), recorded_at=BASE + timedelta(days=1))
    assert snapshot.session_incarnation == "incarnation-1"
    assert {record.record_id for record in snapshot.records} == {"default"}
    sensitive = model.query(
        valid_at=BASE + timedelta(days=1), recorded_at=BASE + timedelta(days=1), include_sensitive=True
    )
    assert {record.record_id for record in sensitive} == {"default", "secret"}


def test_promotion_status_is_typed_and_not_a_verification_bypass() -> None:
    model = OperationalSelfModel()
    model.append(_record("proposal", evidence_verified=False, promotion=PromotionStatus.PROPOSED))
    result = model.verify("proposal", now=BASE + timedelta(hours=1))
    assert result.verified is False
    assert model.query(valid_at=BASE + timedelta(hours=1), recorded_at=BASE + timedelta(hours=1)) == ()
