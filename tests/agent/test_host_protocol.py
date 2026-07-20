from __future__ import annotations

import pytest

from agent import host_protocol
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
        "workspace_observation_schema": "simplicio.workspace-observation/v1",
        "workspace_advisory_schema": "simplicio.workspace-advisory/v1",
    }
    assert {"workspace.observe", "workspace.advisory"}.issubset(
        metadata["capabilities"]
    )
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


def test_workspace_observation_produces_fixed_metadata_only_advisories() -> None:
    store = host_protocol.WorkspaceAdvisoryStore(
        max_workspaces=2,
        max_events_per_workspace=4,
    )

    accepted = store.observe(
        workspace_id="client-workspace-1",
        revision=1,
        snapshot={
            "changed_files": 2,
            "diagnostic_errors": 1,
            "diagnostic_warnings": 0,
            "test_status": "not_run",
        },
    )

    assert accepted == {
        "schema": "simplicio.workspace-observation/v1",
        "workspace_id": "client-workspace-1",
        "accepted_revision": 1,
        "published_count": 3,
        "next_cursor": 3,
        "effect": "none",
    }
    replay = store.replay(workspace_id="client-workspace-1", after=0)
    assert replay["schema"] == "simplicio.workspace-advisory/v1"
    assert replay["workspace_id"] == "client-workspace-1"
    assert replay["next_cursor"] == 3
    assert replay["truncated"] is False
    assert [event["sequence"] for event in replay["events"]] == [1, 2, 3]
    assert [event["kind"] for event in replay["events"]] == [
        "finding",
        "risk",
        "suggestion",
    ]
    assert [event["code"] for event in replay["events"]] == [
        "workspace.changes_present",
        "workspace.diagnostics_errors",
        "workspace.verify_changes",
    ]
    for event in replay["events"]:
        assert event["redaction"] == "metadata_only"
        assert event["effect"] == "none"
        assert event["workspace_id"] == "client-workspace-1"
        assert event["observation_revision"] == 1


def test_workspace_observation_rejects_content_and_bad_revision_atomically() -> None:
    store = host_protocol.WorkspaceAdvisoryStore(
        max_workspaces=1,
        max_events_per_workspace=2,
    )
    snapshot = {
        "changed_files": 1,
        "diagnostic_errors": 0,
        "diagnostic_warnings": 0,
        "test_status": "unknown",
        "path": "/private/secret.py",
    }

    with pytest.raises(ValueError, match="metadata-only allowlist") as rejected:
        store.observe(workspace_id="workspace-a", revision=1, snapshot=snapshot)
    assert "/private/secret.py" not in str(rejected.value)

    metadata_only = {
        "changed_files": 0,
        "diagnostic_errors": 0,
        "diagnostic_warnings": 0,
        "test_status": "unknown",
    }
    with pytest.raises(ValueError, match="revision must equal 1"):
        store.observe(
            workspace_id="workspace-a",
            revision=2,
            snapshot=metadata_only,
        )

    accepted = store.observe(
        workspace_id="workspace-b",
        revision=1,
        snapshot=metadata_only,
    )
    assert accepted["workspace_id"] == "workspace-b"
    assert accepted["published_count"] == 0
    with pytest.raises(ValueError, match="capacity is full"):
        store.observe(
            workspace_id="workspace-c",
            revision=1,
            snapshot=metadata_only,
        )


def test_workspace_replay_is_bounded_strict_and_isolated() -> None:
    store = host_protocol.WorkspaceAdvisoryStore(
        max_workspaces=2,
        max_events_per_workspace=2,
    )
    store.observe(
        workspace_id="workspace-a",
        revision=1,
        snapshot={
            "changed_files": 2,
            "diagnostic_errors": 1,
            "diagnostic_warnings": 0,
            "test_status": "not_run",
        },
    )
    store.observe(
        workspace_id="workspace-b",
        revision=1,
        snapshot={
            "changed_files": 0,
            "diagnostic_errors": 0,
            "diagnostic_warnings": 0,
            "test_status": "passing",
        },
    )

    first = store.replay(workspace_id="workspace-a", after=0)
    assert [event["sequence"] for event in first["events"]] == [2, 3]
    assert first["next_cursor"] == 3
    assert first["truncated"] is True
    isolated = store.replay(workspace_id="workspace-b", after=0)
    assert [event["sequence"] for event in isolated["events"]] == [1]
    assert isolated["events"][0]["code"] == "workspace.tests_passing"

    first["events"][0]["facts"].clear()
    repeated = store.replay(workspace_id="workspace-a", after=1)
    assert repeated["events"][0]["facts"] == {"diagnostic_errors": 1}
    empty = store.replay(workspace_id="workspace-a", after=3)
    assert empty["events"] == []
    assert empty["next_cursor"] == 3
    with pytest.raises(ValueError, match="exceeds the current workspace"):
        store.replay(workspace_id="workspace-a", after=4)
    with pytest.raises(ValueError, match="non-negative integer"):
        store.replay(workspace_id="workspace-a", after=True)
    with pytest.raises(ValueError, match="revision must equal 2"):
        store.observe(
            workspace_id="workspace-a",
            revision=1,
            snapshot={
                "changed_files": 0,
                "diagnostic_errors": 0,
                "diagnostic_warnings": 0,
                "test_status": "unknown",
            },
        )


@pytest.mark.parametrize(
    ("workspace_id", "snapshot"),
    [
        (
            "/private/workspace",
            {
                "changed_files": 0,
                "diagnostic_errors": 0,
                "diagnostic_warnings": 0,
                "test_status": "unknown",
            },
        ),
        (
            "workspace-a",
            {
                "changed_files": True,
                "diagnostic_errors": 0,
                "diagnostic_warnings": 0,
                "test_status": "unknown",
            },
        ),
        (
            "workspace-a",
            {
                "changed_files": 0,
                "diagnostic_errors": 0,
                "diagnostic_warnings": 0,
                "test_status": "raw-output",
            },
        ),
    ],
)
def test_workspace_observation_rejects_paths_and_non_metadata_values(
    workspace_id: str,
    snapshot: dict[str, object],
) -> None:
    store = host_protocol.WorkspaceAdvisoryStore()

    with pytest.raises(ValueError):
        store.observe(workspace_id=workspace_id, revision=1, snapshot=snapshot)
