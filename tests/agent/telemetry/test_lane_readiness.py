"""Tests for ``agent.telemetry.lane_readiness`` (issue #142)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.telemetry.lane_readiness import (
    ArtifactStatus,
    BlockReason,
    LockInfo,
    LockStatus,
    ReadinessState,
    evaluate_lane_readiness,
    record_lane_readiness_receipt,
)

NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_no_artifacts_is_blocked_with_artifacts_missing() -> None:
    receipt = evaluate_lane_readiness(lane_id="lane-1", now=NOW)
    assert receipt.state is ReadinessState.BLOCKED
    assert receipt.blocked is True
    assert BlockReason.ARTIFACTS_MISSING.value in receipt.reasons


def test_missing_artifact_is_blocked() -> None:
    receipt = evaluate_lane_readiness(
        lane_id="lane-1",
        artifacts=[
            ArtifactStatus(name="project-map", present=True, fresh=True),
            ArtifactStatus(name="symbol-index", present=False),
        ],
        now=NOW,
    )
    assert receipt.state is ReadinessState.BLOCKED
    assert receipt.reasons == [BlockReason.ARTIFACTS_MISSING.value]


def test_stale_artifact_is_blocked_with_not_fresh() -> None:
    receipt = evaluate_lane_readiness(
        lane_id="lane-1",
        artifacts=[ArtifactStatus(name="project-map", present=True, fresh=False)],
        now=NOW,
    )
    assert receipt.state is ReadinessState.BLOCKED
    assert receipt.reasons == [BlockReason.ARTIFACTS_NOT_FRESH.value]


def test_stale_lock_blocks_even_with_fresh_artifacts() -> None:
    stale_lock = LockInfo(
        holder="worker-a",
        acquired_at=_iso(NOW - timedelta(hours=2)),
        heartbeat_at=_iso(NOW - timedelta(hours=1)),  # older than the 15m TTL
    )
    receipt = evaluate_lane_readiness(
        lane_id="lane-1",
        artifacts=[ArtifactStatus(name="project-map", present=True, fresh=True)],
        lock=stale_lock,
        now=NOW,
    )
    assert receipt.lock_status is LockStatus.STALE
    assert receipt.state is ReadinessState.BLOCKED
    assert BlockReason.LOCK_STALE.value in receipt.reasons


def test_legitimate_lock_does_not_block() -> None:
    live_lock = LockInfo(
        holder="worker-a",
        acquired_at=_iso(NOW - timedelta(minutes=30)),
        heartbeat_at=_iso(NOW - timedelta(seconds=5)),
    )
    receipt = evaluate_lane_readiness(
        lane_id="lane-1",
        artifacts=[ArtifactStatus(name="project-map", present=True, fresh=True)],
        lock=live_lock,
        handoff_targets=["pr-branch"],
        now=NOW,
    )
    assert receipt.lock_status is LockStatus.LEGITIMATE
    assert receipt.state is ReadinessState.HANDOFF_READY
    assert receipt.reasons == []


def test_missing_context_surface_is_named_explicitly() -> None:
    receipt = evaluate_lane_readiness(
        lane_id="lane-1",
        artifacts=[ArtifactStatus(name="project-map", present=True, fresh=True)],
        required_context=["call-graph", "precedent-index"],
        available_context=["call-graph"],
        now=NOW,
    )
    assert receipt.state is ReadinessState.BLOCKED
    assert BlockReason.NEEDS_BROADER_CONTEXT.value in receipt.reasons
    assert receipt.missing_context == ["precedent-index"]


def test_lane_transitions_blocked_to_artifacts_ready_to_handoff_ready(
    tmp_path: Path,
) -> None:
    """The transition the acceptance criteria calls out explicitly."""

    # 1. blocked -- artifacts missing entirely.
    blocked = evaluate_lane_readiness(lane_id="lane-142", now=NOW)
    assert blocked.state is ReadinessState.BLOCKED
    assert blocked.reasons == [BlockReason.ARTIFACTS_MISSING.value]
    blocked_saved = record_lane_readiness_receipt(blocked, directory=tmp_path)
    assert blocked_saved.status == "blocked"

    # 2. artifacts_ready -- artifacts now present+fresh, lock legitimate,
    #    context satisfied, but no handoff target declared yet.
    live_lock = LockInfo(
        holder="mapper",
        acquired_at=_iso(NOW - timedelta(minutes=1)),
        heartbeat_at=_iso(NOW),
    )
    artifacts_ready = evaluate_lane_readiness(
        lane_id="lane-142",
        artifacts=[
            ArtifactStatus(name="project-map", present=True, fresh=True),
            ArtifactStatus(name="symbol-index", present=True, fresh=True),
        ],
        lock=live_lock,
        required_context=["call-graph"],
        available_context=["call-graph"],
        now=NOW,
    )
    assert artifacts_ready.state is ReadinessState.ARTIFACTS_READY
    assert artifacts_ready.artifacts_ready is True
    assert artifacts_ready.handoff_ready is False
    assert artifacts_ready.reasons == [BlockReason.NO_HANDOFF_TARGETS.value]
    artifacts_ready_saved = record_lane_readiness_receipt(artifacts_ready, directory=tmp_path)
    assert artifacts_ready_saved.status == "ok"

    # 3. handoff_ready -- a handoff target now exists.
    handoff_ready = evaluate_lane_readiness(
        lane_id="lane-142",
        artifacts=[
            ArtifactStatus(name="project-map", present=True, fresh=True),
            ArtifactStatus(name="symbol-index", present=True, fresh=True),
        ],
        lock=live_lock,
        required_context=["call-graph"],
        available_context=["call-graph"],
        handoff_targets=["origin/agent/issue-142"],
        now=NOW,
    )
    assert handoff_ready.state is ReadinessState.HANDOFF_READY
    assert handoff_ready.handoff_ready is True
    assert handoff_ready.reasons == []
    handoff_ready_saved = record_lane_readiness_receipt(handoff_ready, directory=tmp_path)
    assert handoff_ready_saved.status == "ok"

    # Each state produced a distinct, independently-readable receipt file.
    assert blocked_saved.sha != artifacts_ready_saved.sha != handoff_ready_saved.sha
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_to_dict_is_json_serializable_and_machine_readable() -> None:
    receipt = evaluate_lane_readiness(
        lane_id="lane-1",
        artifacts=[ArtifactStatus(name="project-map", present=False)],
        now=NOW,
    )
    data = receipt.to_dict()
    assert data["state"] == "blocked"
    assert data["reasons"] == ["artifacts_missing"]
    assert data["artifacts"][0] == {
        "name": "project-map",
        "present": False,
        "fresh": True,
        "detail": None,
    }
