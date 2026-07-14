"""Focused golden tests for the bounded daemon hot-path contract."""

import json
from pathlib import Path

import pytest

from tools.daemon_hot_path import (
    DAEMON_HOT_PATH_SCHEMA,
    CrashReceipt,
    DaemonEvent,
    DaemonHotPathController,
    DaemonPhase,
    DaemonReconnectPolicy,
    DaemonRollbackPlan,
    DaemonStartup,
    DaemonState,
    classify_health,
    guarded_call,
    plan_rollback,
)


FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "native" / "daemon_hot_path_contract.json"
)


def test_startup_is_versioned_and_json_safe():
    startup = DaemonStartup("desktop", generation=2)

    assert startup.to_dict() == {
        "schema": DAEMON_HOT_PATH_SCHEMA,
        "op": "startup",
        "profile": "desktop",
        "protocol_version": 1,
        "generation": 2,
    }
    assert json.loads(json.dumps(startup.to_dict())) == startup.to_dict()


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (None, "invalid_response"),
        ({"ok": False, "error": "cold", "fallback": "cold"}, "daemon_error"),
        ({"ok": True, "profile": "desktop"}, "protocol_unreported"),
        (
            {"ok": True, "profile": "desktop", "protocol_version": 2},
            "protocol_incompatible",
        ),
        ({"ok": True, "profile": "car", "protocol_version": 1}, "profile_mismatch"),
    ],
)
def test_health_fails_closed_for_missing_or_incompatible_status(response, reason):
    health = classify_health(response, expected_profile="desktop")

    assert health.ready is False
    assert health.reason_code == reason


def test_health_accepts_current_status_and_host_boundary():
    health = classify_health(
        {
            "ok": True,
            "profile": "desktop",
            "protocol_version": 1,
            "host": {"ready": True, "stopping": False},
        },
        expected_profile="desktop",
    )

    assert health.ready is True
    assert health.protocol_status == "compatible"
    assert health.host_ready is True
    assert health.host_stopping is False


def test_existing_unversioned_daemon_is_not_claimed_native_ready():
    health = classify_health(
        {"ok": True, "profile": "car", "caches": ["tool_registry"]},
        expected_profile="car",
    )

    assert health.ready is False
    assert health.protocol_status == "unreported"


def test_reconnect_is_bounded_and_delays_are_deterministic():
    controller = DaemonHotPathController(
        DaemonReconnectPolicy(max_attempts=2, delays_ms=(10, 20))
    )
    ready = DaemonState(DaemonPhase.READY)

    first = controller.step(ready, DaemonEvent.DISCONNECTED, error="socket closed")
    second = controller.step(first.state, DaemonEvent.RECONNECT_FAILED, error="timeout")
    exhausted = controller.step(
        second.state, DaemonEvent.RECONNECT_FAILED, error="timeout"
    )

    assert (first.phase, first.retry, first.retry_delay_ms) == (
        DaemonPhase.RECONNECTING,
        True,
        10,
    )
    assert (second.phase, second.retry_delay_ms) == (
        DaemonPhase.RECONNECTING,
        20,
    )
    assert exhausted.phase is DaemonPhase.FAILED
    assert exhausted.retry is False


def test_startup_health_reconnect_crash_and_stop_are_reducer_events():
    controller = DaemonHotPathController()
    starting = controller.step(DaemonState(), DaemonEvent.START)
    ready = controller.step(
        starting.state, DaemonEvent.HEALTHY, protocol_status="compatible"
    )
    reconnecting = controller.step(ready.state, DaemonEvent.CRASHED, error="worker")
    recovered = controller.step(
        reconnecting.state,
        DaemonEvent.RECONNECT_SUCCEEDED,
        protocol_status="compatible",
    )
    stopped = controller.step(recovered.state, DaemonEvent.STOPPED)

    assert starting.phase is DaemonPhase.STARTING
    assert ready.phase is DaemonPhase.READY
    assert reconnecting.phase is DaemonPhase.RECONNECTING
    assert recovered.state.generation == 1
    assert stopped.phase is DaemonPhase.STOPPED


def test_crash_isolation_returns_secret_free_receipt():
    def fail():
        raise RuntimeError("provider token must not be serialized")

    result, receipt = guarded_call(fail)

    assert result is None
    assert receipt == CrashReceipt(True, "RuntimeError")
    assert "provider token" not in json.dumps(receipt.to_dict())


def test_successful_guarded_call_preserves_result():
    assert guarded_call(lambda value: value + 1, 4) == (5, None)


@pytest.mark.parametrize(
    ("previous", "compatible", "allowed", "reason"),
    [
        (None, True, False, "no_previous_version"),
        ("v1", False, False, "previous_protocol_incompatible"),
        ("v1", True, True, "rollback_available"),
    ],
)
def test_rollback_requires_distinct_compatible_previous_version(
    previous, compatible, allowed, reason
):
    plan = plan_rollback("v2", previous, previous_protocol_compatible=compatible)

    assert plan.allowed is allowed
    assert plan.reason_code == reason
    assert isinstance(plan, DaemonRollbackPlan)


def test_rollback_events_are_explicit_and_json_safe():
    controller = DaemonHotPathController()
    requested = controller.step(
        DaemonState(DaemonPhase.FAILED), DaemonEvent.ROLLBACK_REQUESTED
    )
    completed = controller.step(
        requested.state,
        DaemonEvent.ROLLBACK_SUCCEEDED,
        protocol_status="compatible",
    )

    assert requested.phase is DaemonPhase.ROLLING_BACK
    assert completed.phase is DaemonPhase.ROLLED_BACK
    assert json.loads(json.dumps(completed.to_dict())) == completed.to_dict()


def test_golden_fixture_matches_wire_contract():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    startup = DaemonStartup(**fixture["startup"])
    decision = DaemonHotPathController(DaemonReconnectPolicy(**fixture["policy"])).step(
        DaemonState(), DaemonEvent.START
    )

    assert startup.to_dict() == fixture["startup_wire"]
    assert decision.to_dict() == fixture["startup_decision"]
