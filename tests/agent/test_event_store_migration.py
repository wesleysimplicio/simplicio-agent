"""Focused tests for the issue #517 operational-state migration slice."""

from __future__ import annotations

import hashlib
import json

import pytest

import agent.event_store as event_store
from agent.belief_state import BeliefType, Freshness
from agent.event_store import (
    AwarenessReceipt,
    OperationalScope,
    OperationalValueStatus,
    migrate_legacy_event_store,
    read_migrated_event_store,
)


@pytest.fixture
def scope() -> OperationalScope:
    return OperationalScope(profile_id="profile-1", tenant_id="tenant-1")


def _receipt(scope: OperationalScope, receipt_id: str = "receipt-1") -> AwarenessReceipt:
    return AwarenessReceipt(
        receipt_id=receipt_id,
        path="agent.operational_now",
        value={"answer": 42, "labels": ["stable", "local"]},
        status=OperationalValueStatus.MEASURED,
        freshness=Freshness.FRESH,
        source="test",
        source_event_id=f"event-{receipt_id}",
        recorded_at_ns=1_700_000_000_000_000_000,
        belief_type=BeliefType.OBSERVED,
        confidence=0.9,
        uncertainty=0.1,
        distribution=(("yes", 0.9), ("no", 0.1)),
        conflicts=("old-value",),
        evidence_handles=("hbp:1",),
        payload={
            "profile_id": scope.profile_id,
            "tenant_id": scope.tenant_id,
            "nested": {"value": True},
        },
    )


def _write_legacy(path, receipts: list[AwarenessReceipt]) -> None:
    path.write_text(
        "".join(json.dumps(item.to_dict(), sort_keys=True) + "\n" for item in receipts),
        encoding="utf-8",
    )


def test_migrates_and_round_trips_existing_receipt_type(tmp_path, scope):
    legacy = tmp_path / "events.jsonl"
    target = tmp_path / "events"
    receipts = [_receipt(scope), _receipt(scope, "receipt-2")]
    _write_legacy(legacy, receipts)

    report = migrate_legacy_event_store(legacy, target, scope=scope)

    assert report.migrated is True
    assert report.ok
    assert report.receipt_count == 2
    assert target.with_suffix(".hbp").exists()
    assert target.with_suffix(".hbi").exists()
    assert target.with_suffix(".migration").read_text(encoding="utf-8").startswith(
        "schema=simplicio.operational-event-store-migration/v1\n"
    )
    assert read_migrated_event_store(target, scope=scope) == receipts


def test_migration_is_idempotent_for_same_source_digest(tmp_path, scope):
    legacy = tmp_path / "events.jsonl"
    target = tmp_path / "events"
    _write_legacy(legacy, [_receipt(scope)])

    first = migrate_legacy_event_store(legacy, target, scope=scope)
    hbp_before = target.with_suffix(".hbp").read_bytes()
    hbi_before = target.with_suffix(".hbi").read_bytes()
    second = migrate_legacy_event_store(legacy, target, scope=scope)

    assert first.migrated is True
    assert second.already_migrated is True
    assert second.migrated is False
    assert target.with_suffix(".hbp").read_bytes() == hbp_before
    assert target.with_suffix(".hbi").read_bytes() == hbi_before


@pytest.mark.parametrize("raw", [b'{"receipt_id":"truncated"', b"not-json\n"])
def test_corrupt_or_truncated_legacy_input_does_not_create_target(tmp_path, scope, raw):
    legacy = tmp_path / "events.jsonl"
    target = tmp_path / "events"
    legacy.write_bytes(raw)

    report = migrate_legacy_event_store(legacy, target, scope=scope)

    assert report.migrated is False
    assert report.errors
    assert not target.with_suffix(".hbp").exists()
    assert not target.with_suffix(".hbi").exists()


def test_interrupted_publish_is_recovered_on_retry(tmp_path, scope):
    legacy = tmp_path / "events.jsonl"
    target = tmp_path / "events"
    _write_legacy(legacy, [_receipt(scope)])
    digest = hashlib.sha256(legacy.read_bytes()).hexdigest()

    target.with_suffix(".hbp").write_text("partial", encoding="utf-8")
    target.with_suffix(".migration.pending").write_text(
        "schema=simplicio.operational-event-store-migration/v1\n"
        f"source_sha256={digest}\n",
        encoding="utf-8",
    )

    report = migrate_legacy_event_store(legacy, target, scope=scope)

    assert report.migrated is True
    assert read_migrated_event_store(target, scope=scope) == [_receipt(scope)]
    assert not target.with_suffix(".migration.pending").exists()


def test_failed_second_replace_rolls_back_first_replace(tmp_path, scope, monkeypatch):
    legacy = tmp_path / "events.jsonl"
    target = tmp_path / "events"
    _write_legacy(legacy, [_receipt(scope)])
    real_replace = event_store.os.replace

    def fail_hbi_replace(source, destination):
        if destination == target.with_suffix(".hbi"):
            raise OSError("simulated interrupted HBI publication")
        return real_replace(source, destination)

    monkeypatch.setattr(event_store.os, "replace", fail_hbi_replace)

    report = migrate_legacy_event_store(legacy, target, scope=scope)

    assert report.migrated is False
    assert report.rolled_back is True
    assert report.errors
    assert not target.with_suffix(".hbp").exists()
    assert not target.with_suffix(".hbi").exists()
    assert not target.with_suffix(".migration").exists()
    assert not target.with_suffix(".migration.pending").exists()
