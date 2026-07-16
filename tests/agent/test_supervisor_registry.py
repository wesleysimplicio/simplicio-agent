from __future__ import annotations

import json

import pytest

from agent.supervisor_registry import (
    REGISTRY_SCHEMA,
    SupervisorConflict,
    SupervisorRegistry,
    hardware_fingerprint,
)


def test_hardware_fingerprint_is_deterministic_and_does_not_expose_inputs():
    first = hardware_fingerprint(machine="test-machine", processor="cpu", node=42, cpu_count=8, salt="test")
    second = hardware_fingerprint(machine="test-machine", processor="cpu", node=42, cpu_count=8, salt="test")
    assert first == second
    assert first.startswith("sha256:")
    assert "test-machine" not in first
    assert "42" not in first


def test_registry_register_is_idempotent_and_persisted(tmp_path):
    registry = SupervisorRegistry(tmp_path / "supervisors.json")
    first = registry.register("sup-a", role="planner", capabilities=("fanout", "observe"), fingerprint="sha256:a", now_ns=1)
    second = registry.register("sup-a", role="planner", capabilities=("observe", "fanout"), fingerprint="sha256:a", now_ns=2)

    assert first.hardware_fingerprint == second.hardware_fingerprint
    assert registry.get("sup-a") == second
    assert [item.supervisor_id for item in registry.list()] == ["sup-a"]
    payload = json.loads((tmp_path / "supervisors.json").read_text(encoding="utf-8"))
    assert payload["schema"] == REGISTRY_SCHEMA
    assert payload["supervisors"]["sup-a"]["capabilities"] == ["fanout", "observe"]


def test_registry_rejects_hardware_identity_reuse_and_supports_removal(tmp_path):
    registry = SupervisorRegistry(tmp_path / "supervisors.json")
    registry.register("sup-a", role="planner", fingerprint="sha256:a", now_ns=1)

    with pytest.raises(SupervisorConflict):
        registry.register("sup-a", role="planner", fingerprint="sha256:b", now_ns=2)

    assert registry.unregister("sup-a") is True
    assert registry.unregister("sup-a") is False
