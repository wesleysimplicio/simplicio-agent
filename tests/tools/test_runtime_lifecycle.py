"""Focused contract tests for the managed Runtime lifecycle/readiness slice."""

from unittest.mock import Mock

import pytest

from tools.runtime_lifecycle import (
    LIFECYCLE_SCHEMA,
    LifecycleEvent,
    LifecyclePhase,
    LifecycleState,
    ReadinessProbes,
    ReconnectPolicy,
    RuntimeLifecycleController,
    RuntimeLifecycleManager,
)
from tools.runtime_manager import RuntimeStatus


def _status(
    *,
    present=True,
    satisfied=True,
    version="3.4.0",
    minimum="3.4.0",
    source="managed",
    detail="",
):
    return RuntimeStatus(
        "/managed/simplicio" if present else None,
        source if present else "absent",
        version if present else None,
        minimum,
        satisfied,
        detail=detail,
    )


def _ready_probes(**overrides):
    base = {
        "health_ready": True,
        "migrations_ready": True,
        "seed_ready": True,
        "neural_db_ready": True,
    }
    base.update(overrides)
    return ReadinessProbes(**base)


def test_binary_presence_alone_is_not_ready():
    manager = RuntimeLifecycleManager(lambda: _status())

    result = manager.readiness()

    assert result.phase is LifecyclePhase.NOT_READY
    assert result.reason_code == "runtime_health_not_ready"
    assert not result.ready


def test_absent_runtime_is_fail_closed_with_repair_plan():
    result = RuntimeLifecycleManager(lambda: _status(present=False)).readiness()

    assert result.phase is LifecyclePhase.ABSENT
    assert result.reason_code == "runtime_absent"
    assert result.repair_plan == (
        "run `simplicio-agent doctor --fix` to install the managed runtime",
    )
    assert not result.ready


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (
            _status(
                satisfied=False,
                version="3.3.0",
                detail="installed 3.3.0 < pinned 3.4.0",
            ),
            "blocked_incompatible_runtime",
        ),
        (
            _status(
                satisfied=False,
                version="9.0.0",
                detail="installed 9.0.0 outside supported protocol range",
            ),
            "blocked_incompatible_runtime",
        ),
        (
            _status(
                satisfied=False,
                version=None,
                detail="binary resolved but --version handshake failed",
            ),
            "blocked_runtime_handshake",
        ),
    ],
)
def test_incompatible_or_unverified_runtime_is_blocked(status, reason):
    result = RuntimeLifecycleManager(lambda: status).readiness(_ready_probes())

    assert result.phase is LifecyclePhase.BLOCKED
    assert result.reason_code == reason
    assert result.detail == status.detail
    assert result.repair_plan
    assert not result.ready


@pytest.mark.parametrize(
    ("probe_name", "reason"),
    [
        ("health_ready", "runtime_health_not_ready"),
        ("migrations_ready", "migrations_not_ready"),
        ("seed_ready", "seed_not_ready"),
        ("neural_db_ready", "neural_db_not_ready"),
    ],
)
def test_health_and_state_probes_have_separate_reason_codes(probe_name, reason):
    probes = _ready_probes(**{probe_name: False})

    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.NOT_READY
    assert result.reason_code == reason
    assert not result.ready


def test_required_schema_failure_blocks_readiness():
    probes = _ready_probes(
        required_schemas={
            "simplicio-runtime/migrations/v1": True,
            "simplicio-runtime/neural-db/v1": False,
        }
    )

    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.NOT_READY
    assert result.reason_code == "required_schema_missing"
    assert "neural-db" in result.detail


def test_required_capability_failure_blocks_readiness():
    probes = _ready_probes(
        required_capabilities={"seed": True, "neural_db": False},
    )

    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.NOT_READY
    assert result.reason_code == "required_capability_unhealthy"
    assert "neural_db" in result.detail


def test_optional_capability_failure_is_ready_but_degraded():
    probes = _ready_probes(optional_capabilities={"embeddings": False})

    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.DEGRADED
    assert result.reason_code == "optional_capability_unhealthy"
    assert result.ready


def test_ready_result_has_stable_wire_shape_and_no_runtime_path():
    probes = _ready_probes(
        required_schemas={"simplicio-runtime/migrations/v1": True},
        required_capabilities={"seed": True},
    )
    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.READY
    assert result.as_dict() == {
        "schema": "simplicio.agent-runtime-handshake/v1",
        "phase": "ready",
        "reason_code": "ready",
        "requested_min_version": "3.4.0",
        "runtime_version": "3.4.0",
        "selected_source": "managed",
        "binary_resolved": True,
        "binary_compatible": True,
        "health_ready": True,
        "migrations_ready": True,
        "seed_ready": True,
        "neural_db_ready": True,
        "required_schemas": {"simplicio-runtime/migrations/v1": True},
        "required_capabilities": {"seed": True},
        "optional_capabilities": {},
        "repair_plan": [],
        "ready": True,
        "detail": "",
    }
    assert "/managed/simplicio" not in result.as_dict()


def test_probe_mappings_are_snapshotted():
    required = {"seed": True}
    schemas = {"simplicio-runtime/migrations/v1": True}
    probes = _ready_probes(
        required_schemas=schemas,
        required_capabilities=required,
    )
    required["seed"] = False
    schemas["simplicio-runtime/migrations/v1"] = False

    assert probes.required_capabilities["seed"] is True
    assert probes.required_schemas["simplicio-runtime/migrations/v1"] is True


def test_status_provider_is_called_once_per_snapshot():
    provider = Mock(return_value=_status())
    manager = RuntimeLifecycleManager(provider)

    manager.readiness(_ready_probes())

    provider.assert_called_once_with()


def test_lifecycle_start_health_and_protocol_are_fail_closed():
    controller = RuntimeLifecycleController(
        ReconnectPolicy(max_attempts=2, delays_ms=(10, 20))
    )
    state = LifecycleState()

    starting = controller.step(state, LifecycleEvent.START)
    assert starting.phase is LifecyclePhase.STARTING
    ready = controller.step(
        starting.state, LifecycleEvent.HEALTHY, protocol_status="compatible"
    )
    assert ready.phase is LifecyclePhase.READY
    assert ready.state.reconnect_attempts == 0
    failed = controller.step(
        ready.state, LifecycleEvent.HEALTHY, protocol_status="incompatible"
    )
    assert failed.phase is LifecyclePhase.FAILED
    assert not failed.retry
    assert failed.reason == "protocol_incompatible"


def test_lifecycle_reconnect_is_bounded_and_uses_deterministic_delays():
    controller = RuntimeLifecycleController(
        ReconnectPolicy(max_attempts=2, delays_ms=(10, 20))
    )
    state = LifecycleState(LifecyclePhase.READY)

    first = controller.step(state, LifecycleEvent.DISCONNECTED, error="socket closed")
    assert (first.phase, first.retry, first.retry_delay_ms) == (
        LifecyclePhase.RECONNECTING,
        True,
        10,
    )
    second = controller.step(
        first.state, LifecycleEvent.RECONNECT_FAILED, error="timeout"
    )
    assert (second.phase, second.retry, second.retry_delay_ms) == (
        LifecyclePhase.RECONNECTING,
        True,
        20,
    )
    exhausted = controller.step(
        second.state, LifecycleEvent.RECONNECT_FAILED, error="timeout"
    )
    assert exhausted.phase is LifecyclePhase.FAILED
    assert not exhausted.retry
    assert exhausted.retry_delay_ms is None


def test_lifecycle_reconnect_success_increments_generation_and_stop_is_terminal():
    controller = RuntimeLifecycleController()
    state = LifecycleState(
        LifecyclePhase.RECONNECTING, reconnect_attempts=1, generation=4
    )

    recovered = controller.step(state, LifecycleEvent.RECONNECT_SUCCEEDED)
    assert recovered.phase is LifecyclePhase.READY
    assert recovered.state == LifecycleState(LifecyclePhase.READY, generation=5)
    stopping = controller.step(recovered.state, LifecycleEvent.STOP_REQUESTED)
    stopped = controller.step(stopping.state, LifecycleEvent.STOPPED)
    assert stopping.phase is LifecyclePhase.STOPPING
    assert stopped.phase is LifecyclePhase.STOPPED


def test_lifecycle_decision_wire_shape_is_stable_and_json_safe():
    decision = RuntimeLifecycleController().step(LifecycleState(), LifecycleEvent.START)
    assert decision.to_dict() == {
        "schema": LIFECYCLE_SCHEMA,
        "phase": "starting",
        "state": {
            "phase": "starting",
            "reconnect_attempts": 0,
            "generation": 0,
            "last_error": "",
        },
        "retry": False,
        "retry_delay_ms": None,
        "reason": "startup_requested",
        "protocol_status": "unreported",
    }


def test_readiness_receipt_has_stable_content_hash():
    manager = RuntimeLifecycleManager(lambda: _status())
    first = manager.readiness(_ready_probes())
    replay = manager.readiness(_ready_probes())

    assert first.ready
    assert first.content_hash() == replay.content_hash()
    assert len(first.content_hash()) == 64
