"""Focused contract tests for the typed Agent<->Runtime handshake slice."""

from datetime import datetime, timedelta, timezone

import pytest

from tools.runtime_handshake import (
    CompatibilityMatrix,
    DEFAULT_HANDSHAKE_TTL_SECONDS,
    DEFAULT_PROTOCOL_RANGE,
    MAX_HANDSHAKE_TTL_SECONDS,
    HANDSHAKE_PROTOCOL_STATUS_UNREPORTED,
    HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME,
    HANDSHAKE_REASON_READY,
    ProtocolRange,
    RuntimeHandshake,
    build_runtime_handshake,
    protocol_range_from_lock,
)


def test_compatibility_matrix_is_machine_readable_and_fail_closed():
    matrix = CompatibilityMatrix(
        agent_protocol=ProtocolRange(1, 2),
        runtime_protocol=ProtocolRange(2, 3),
        required_schemas=("simplicio.run-event/v1", "simplicio.execution-context/v1"),
        available_schemas=("simplicio.run-event/v1",),
        migration_ids=("migration-7",),
    )

    assert matrix.compatible is False
    assert matrix.missing_schemas == ("simplicio.execution-context/v1",)
    assert matrix.to_dict()["migration_ids"] == ["migration-7"]
    assert matrix.to_dict()["compatible"] is False


def test_protocol_range_from_lock_defaults_to_v1_when_lock_omits_handshake_range():
    rng = protocol_range_from_lock({"min_version": "3.5.2"})
    assert rng == ProtocolRange(*DEFAULT_PROTOCOL_RANGE)


def test_protocol_range_from_lock_reads_explicit_range():
    rng = protocol_range_from_lock({"handshake_protocol": {"min": 2, "max": 4}})
    assert rng == ProtocolRange(2, 4)


def test_protocol_range_rejects_invalid_bounds():
    with pytest.raises(ValueError):
        ProtocolRange(4, 2)


def test_runtime_handshake_to_dict_is_json_safe_for_legacy_banner_only_runtime():
    handshake = build_runtime_handshake(
        lock={"handshake_protocol": {"min": 1, "max": 2}},
        runtime_version="3.5.2",
        min_runtime_version="3.5.2",
        bin_path="/bin/simplicio",
        source="path",
        healthy=True,
        reason_code=HANDSHAKE_REASON_READY,
        reason_detail="",
    )

    data = handshake.to_dict()
    assert data["schema"] == "simplicio.agent-runtime-handshake/v1"
    assert data["agent_protocol"] == {"min": 1, "max": 2}
    assert data["runtime_protocol"] is None
    assert data["protocol_status"] == HANDSHAKE_PROTOCOL_STATUS_UNREPORTED
    assert data["reason_code"] == HANDSHAKE_REASON_READY


def test_runtime_handshake_marks_incompatible_protocol_when_runtime_reports_non_overlapping_range():
    handshake = build_runtime_handshake(
        lock={"handshake_protocol": {"min": 3, "max": 4}},
        runtime_version="3.5.2",
        min_runtime_version="3.5.2",
        bin_path="/bin/simplicio",
        source="path",
        healthy=False,
        reason_code=HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME,
        reason_detail="protocol mismatch",
        runtime_protocol=ProtocolRange(1, 2),
    )

    assert handshake.protocol_status == HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME


def test_runtime_handshake_has_bounded_verifiable_validity_window():
    issued_at = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    handshake = build_runtime_handshake(
        lock=None,
        runtime_version="3.5.2",
        min_runtime_version="3.5.2",
        bin_path="/bin/simplicio",
        source="path",
        healthy=True,
        reason_code=HANDSHAKE_REASON_READY,
        reason_detail="",
        issued_at=issued_at,
        ttl_seconds=5,
    )

    data = handshake.to_dict()
    assert data["issued_at"] == "2026-07-14T12:00:00Z"
    assert data["expires_at"] == "2026-07-14T12:00:05Z"
    assert handshake.is_fresh(at=issued_at)
    assert handshake.is_fresh(at=issued_at + timedelta(seconds=4))
    assert not handshake.is_fresh(at=issued_at - timedelta(microseconds=1))
    assert not handshake.is_fresh(at=issued_at + timedelta(seconds=5))


@pytest.mark.parametrize("ttl_seconds", [True, 0, -1, MAX_HANDSHAKE_TTL_SECONDS + 1])
def test_runtime_handshake_rejects_invalid_validity_bounds(ttl_seconds):
    with pytest.raises(ValueError, match="ttl_seconds"):
        build_runtime_handshake(
            lock=None,
            runtime_version="3.5.2",
            min_runtime_version="3.5.2",
            bin_path="/bin/simplicio",
            source="path",
            healthy=True,
            reason_code=HANDSHAKE_REASON_READY,
            reason_detail="",
            ttl_seconds=ttl_seconds,
        )


def test_runtime_handshake_rejects_naive_validity_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_runtime_handshake(
            lock=None,
            runtime_version="3.5.2",
            min_runtime_version="3.5.2",
            bin_path="/bin/simplicio",
            source="path",
            healthy=True,
            reason_code=HANDSHAKE_REASON_READY,
            reason_detail="",
            issued_at=datetime(2026, 7, 14, 12, 0),
        )


def test_runtime_handshake_direct_constructor_keeps_bounded_defaults():
    handshake = RuntimeHandshake(
        runtime_version="3.5.2",
        min_runtime_version="3.5.2",
        bin_path="/bin/simplicio",
        source="path",
        healthy=True,
        reason_code=HANDSHAKE_REASON_READY,
        reason_detail="",
    )

    assert handshake.expires_at - handshake.issued_at == timedelta(
        seconds=DEFAULT_HANDSHAKE_TTL_SECONDS
    )


def test_runtime_handshake_direct_constructor_rejects_unbounded_expiry():
    issued_at = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="validity window"):
        RuntimeHandshake(
            runtime_version="3.5.2",
            min_runtime_version="3.5.2",
            bin_path="/bin/simplicio",
            source="path",
            healthy=True,
            reason_code=HANDSHAKE_REASON_READY,
            reason_detail="",
            issued_at=issued_at,
            expires_at=issued_at
            + timedelta(seconds=MAX_HANDSHAKE_TTL_SECONDS + 1),
        )
