from __future__ import annotations

import pytest

from agent.host_protocol import (
    ADVISORY_SCHEMA,
    AGENT_PROTOCOL_VERSION,
    HOST_CAPABILITIES,
    HOST_PROTOCOL_SCHEMA,
    HOST_PROTOCOL_VERSION,
    HostAdvisoryBuffer,
    host_protocol_metadata,
)
from tools.daemon_hot_path import classify_health


def test_host_protocol_metadata_is_generic_and_code_independent() -> None:
    metadata = host_protocol_metadata("desktop")

    assert metadata == {
        "protocol_schema": HOST_PROTOCOL_SCHEMA,
        "protocol_version": HOST_PROTOCOL_VERSION,
        "agent_protocol": AGENT_PROTOCOL_VERSION,
        "profile": "desktop",
        "capabilities": list(HOST_CAPABILITIES),
        "advisory_schema": ADVISORY_SCHEMA,
    }
    assert "code" not in repr(metadata).lower()


def test_host_protocol_metadata_makes_the_existing_health_gate_ready() -> None:
    response = {
        **host_protocol_metadata("desktop"),
        "ok": True,
        "host": {"ready": True, "stopping": False},
    }

    health = classify_health(response, expected_profile="desktop")

    assert health.ready is True
    assert health.protocol_status == "compatible"


def test_advisory_buffer_replays_after_cursor_without_user_payload() -> None:
    advisories = HostAdvisoryBuffer(max_events=4)
    first = advisories.publish("host.ready")
    second = advisories.publish("host.backpressure")

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    replay = advisories.replay(after=1)
    assert replay == {
        "schema": ADVISORY_SCHEMA,
        "events": [second],
        "next_cursor": 2,
        "truncated": False,
    }
    serialized = repr(replay).lower()
    assert "prompt" not in serialized
    assert "secret" not in serialized


def test_advisory_buffer_is_bounded_and_marks_cursor_gap() -> None:
    advisories = HostAdvisoryBuffer(max_events=2)
    advisories.publish("host.ready")
    advisories.publish("turn.completed")
    latest = advisories.publish("turn.failed")

    replay = advisories.replay(after=0)
    assert [event["sequence"] for event in replay["events"]] == [2, 3]
    assert replay["next_cursor"] == latest["sequence"]
    assert replay["truncated"] is True


def test_advisory_buffer_rejects_unknown_kind_and_bad_cursor() -> None:
    advisories = HostAdvisoryBuffer()

    with pytest.raises(ValueError, match="unknown advisory kind"):
        advisories.publish("workspace.source")
    with pytest.raises(ValueError, match="after must be"):
        advisories.replay(after=-1)


def test_advisory_buffer_rejects_future_cursor_instead_of_losing_events() -> None:
    advisories = HostAdvisoryBuffer()
    advisories.publish("host.ready")

    with pytest.raises(ValueError, match="exceeds the current advisory sequence"):
        advisories.replay(after=10)
