"""Focused contract tests for the managed Runtime readiness projection."""

from unittest.mock import Mock

import pytest

from tools.runtime_lifecycle import (
    LifecyclePhase,
    ReadinessProbes,
    RuntimeLifecycleManager,
)
from tools.runtime_manager import RuntimeStatus


def _status(*, present=True, satisfied=True, version="3.4.0"):
    return RuntimeStatus(
        "/managed/simplicio" if present else None,
        "managed" if present else "absent",
        version if present else None,
        "3.4.0",
        satisfied,
    )


def test_binary_presence_alone_is_not_ready():
    manager = RuntimeLifecycleManager(lambda: _status())

    result = manager.readiness()

    assert result.phase is LifecyclePhase.NOT_READY
    assert result.reason_code == "migrations_not_ready"
    assert not result.ready


def test_absent_runtime_is_explicitly_degraded_from_readiness():
    result = RuntimeLifecycleManager(lambda: _status(present=False)).readiness()

    assert result.phase is LifecyclePhase.ABSENT
    assert result.reason_code == "runtime_absent"
    assert not result.ready


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (_status(satisfied=False, version="3.3.0"), "blocked_incompatible_runtime"),
        (_status(satisfied=False, version=None), "blocked_runtime_handshake"),
    ],
)
def test_incompatible_or_unverified_runtime_is_blocked(status, reason):
    result = RuntimeLifecycleManager(lambda: status).readiness(
        ReadinessProbes(migrations_ready=True, neural_db_ready=True)
    )

    assert result.phase is LifecyclePhase.BLOCKED
    assert result.reason_code == reason
    assert not result.ready


def test_neural_db_is_a_separate_readiness_gate():
    probes = ReadinessProbes(migrations_ready=True)

    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.NOT_READY
    assert result.reason_code == "neural_db_not_ready"


def test_required_capability_failure_blocks_readiness():
    probes = ReadinessProbes(
        migrations_ready=True,
        neural_db_ready=True,
        required_capabilities={"seed": True, "neural_db": False},
    )

    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.NOT_READY
    assert result.reason_code == "required_capability_unhealthy"
    assert "neural_db" in result.detail


def test_optional_capability_failure_is_ready_but_degraded():
    probes = ReadinessProbes(
        migrations_ready=True,
        neural_db_ready=True,
        optional_capabilities={"embeddings": False},
    )

    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.DEGRADED
    assert result.reason_code == "optional_capability_unhealthy"
    assert result.ready


def test_ready_result_has_stable_wire_shape_and_no_runtime_path():
    probes = ReadinessProbes(
        migrations_ready=True,
        neural_db_ready=True,
        required_capabilities={"seed": True},
    )
    result = RuntimeLifecycleManager(lambda: _status()).readiness(probes)

    assert result.phase is LifecyclePhase.READY
    assert result.as_dict() == {
        "schema": "simplicio.agent-runtime-handshake/v1",
        "phase": "ready",
        "reason_code": "ready",
        "runtime_version": "3.4.0",
        "migrations_ready": True,
        "neural_db_ready": True,
        "required_capabilities": {"seed": True},
        "optional_capabilities": {},
        "ready": True,
        "detail": "",
    }
    assert "/managed/simplicio" not in result.as_dict()


def test_probe_mappings_are_snapshotted():
    required = {"seed": True}
    probes = ReadinessProbes(
        migrations_ready=True, neural_db_ready=True, required_capabilities=required
    )
    required["seed"] = False

    assert probes.required_capabilities["seed"] is True


def test_status_provider_is_called_once_per_snapshot():
    provider = Mock(return_value=_status())
    manager = RuntimeLifecycleManager(provider)

    manager.readiness(ReadinessProbes(migrations_ready=True, neural_db_ready=True))

    provider.assert_called_once_with()
