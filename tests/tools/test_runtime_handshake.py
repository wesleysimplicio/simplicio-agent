"""Focused contract tests for the typed Agent<->Runtime handshake slice."""

import pytest

from tools.runtime_handshake import (
    DEFAULT_PROTOCOL_RANGE,
    HANDSHAKE_PROTOCOL_STATUS_UNREPORTED,
    HANDSHAKE_REASON_INCOMPATIBLE_RUNTIME,
    HANDSHAKE_REASON_READY,
    ProtocolRange,
    build_runtime_handshake,
    protocol_range_from_lock,
)


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
