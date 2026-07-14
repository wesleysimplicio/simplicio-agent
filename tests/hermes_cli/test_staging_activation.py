"""Focused Native 2.3 tests for staging, activation, and detached restart."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hermes_cli.staging_activation import (
    AtomicCurrentPointer,
    DetachedRestartHelper,
    DetachedRestartIntent,
    GateName,
    RestartPhase,
    StagingValidationError,
    decide_lock_sync,
    validate_staging,
)


pytestmark = pytest.mark.live_system_guard_bypass


def _staging(root: Path, *, config: object | None = None) -> Path:
    staging = root / "staging"
    package = staging / "hermes_cli"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
    if config is not None:
        (staging / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return staging


def _validated(staging: Path):
    result = validate_staging(
        staging,
        entrypoints=("hermes_cli.config",),
        focused_smoke=lambda path: (path / "hermes_cli" / "config.py").is_file(),
    )
    assert result.passed, result.receipt()
    return result


def test_all_staging_gates_have_independent_receipts_and_logs(tmp_path: Path) -> None:
    staging = _staging(tmp_path, config={"schema": "v1"})
    result = validate_staging(
        staging,
        entrypoints=("hermes_cli.config",),
        config_validator=lambda path, value: value.get("schema") == "v1",
        focused_smoke=lambda path: True,
        log_dir=tmp_path / "logs",
    )

    assert result.passed
    assert {gate.name for gate in result.gates} == set(GateName)
    assert all(gate.log_path and Path(gate.log_path).is_file() for gate in result.gates)
    assert result.digest


def test_failed_gate_keeps_active_tree_untouched(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    (staging / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    active = tmp_path / "active"
    active.mkdir()
    marker = active / "marker"
    marker.write_text("old", encoding="utf-8")

    result = validate_staging(
        staging,
        entrypoints=("hermes_cli.config",),
        focused_smoke=lambda path: True,
    )

    assert not result.passed
    assert result.gates[0].name is GateName.SYNTAX
    assert not result.gates[0].passed
    assert marker.read_text(encoding="utf-8") == "old"


def test_missing_smoke_runner_fails_closed(tmp_path: Path) -> None:
    result = validate_staging(_staging(tmp_path), entrypoints=("hermes_cli.config",))

    assert not result.passed
    assert result.gates[-1].name is GateName.FOCUSED_SMOKE
    assert "required" in result.gates[-1].detail


@pytest.mark.parametrize(
    ("gate", "kwargs"),
    [
        (GateName.IMPORT, {"entrypoints": ("hermes_cli.missing",)}),
        (
            GateName.CONFIG,
            {"config_validator": lambda path, value: False},
        ),
    ],
)
def test_import_and_config_failures_are_individual_blockers(
    tmp_path: Path, gate: GateName, kwargs: dict[str, object]
) -> None:
    staging = _staging(tmp_path, config={"schema": "v1"})
    result = validate_staging(
        staging,
        focused_smoke=lambda path: True,
        **kwargs,
    )

    failed = {receipt.name for receipt in result.gates if not receipt.passed}
    assert failed == {gate}
    assert result.passed is False


def test_focused_smoke_failure_is_an_individual_blocker(tmp_path: Path) -> None:
    result = validate_staging(
        _staging(tmp_path),
        entrypoints=("hermes_cli.config",),
        focused_smoke=lambda path: False,
    )

    assert [gate.name for gate in result.gates if not gate.passed] == [
        GateName.FOCUSED_SMOKE
    ]


def test_default_config_schema_gate_rejects_non_mapping(tmp_path: Path) -> None:
    staging = _staging(tmp_path, config=["not", "a", "mapping"])

    result = validate_staging(
        staging,
        entrypoints=("hermes_cli.config",),
        focused_smoke=lambda path: True,
    )

    assert result.gates[2].name is GateName.CONFIG
    assert result.gates[2].passed is False
    assert "mapping" in result.gates[2].detail


def test_lock_sync_only_when_digest_changes(tmp_path: Path) -> None:
    active = tmp_path / "active"
    staging = tmp_path / "staging"
    active.mkdir()
    staging.mkdir()
    for root in (active, staging):
        (root / "uv.lock").write_text("same", encoding="utf-8")
        (root / "runtime.lock").write_text("same", encoding="utf-8")

    same = decide_lock_sync(staging, active)
    assert same.should_sync is False
    (staging / "runtime.lock").write_text("changed", encoding="utf-8")
    changed = decide_lock_sync(staging, active)
    assert changed.should_sync is True
    assert changed.staging_digest != changed.active_digest


def test_activation_publishes_complete_slots_through_current(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    validation = _validated(staging)
    pointer = AtomicCurrentPointer(tmp_path / "install")

    first = pointer.activate(staging, validation=validation)
    assert pointer.read() == first
    assert (pointer.slots / first.slot / "hermes_cli" / "config.py").is_file()

    (staging / "hermes_cli" / "config.py").write_text("VALUE = 2\n", encoding="utf-8")
    second_validation = _validated(staging)
    second = pointer.activate(staging, validation=second_validation)
    assert second.slot != first.slot
    assert pointer.read() == second
    assert (pointer.slots / first.slot).is_dir()


def test_activation_rejects_staging_mutated_after_validation(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    validation = _validated(staging)
    (staging / "hermes_cli" / "config.py").write_text("VALUE = 3\n", encoding="utf-8")
    pointer = AtomicCurrentPointer(tmp_path / "install")

    with pytest.raises(StagingValidationError, match="changed"):
        pointer.activate(staging, validation=validation)
    assert pointer.read() is None


def test_detached_launch_persists_intent_and_uses_new_session(tmp_path: Path) -> None:
    intent = DetachedRestartIntent(
        old_pid=1234,
        target_slot="slot-next",
        pointer_digest="a" * 64,
        supervisor="test-supervisor",
    )
    helper = DetachedRestartHelper(intent)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    helper.launch(["supervisor-helper"], tmp_path / "restart.json", popen=fake_popen)

    assert (
        json.loads((tmp_path / "restart.json").read_text(encoding="utf-8"))["old_pid"]
        == 1234
    )
    assert calls[0][0] == ["supervisor-helper"]
    if hasattr(subprocess.Popen, "__call__") and "start_new_session" in calls[0][1]:
        assert calls[0][1]["start_new_session"] is True


def test_restart_helper_waits_drain_then_supervisor_then_startup() -> None:
    intent = DetachedRestartIntent(1, "slot-next", "b" * 64, "systemd")
    helper = DetachedRestartHelper(intent)
    events: list[str] = []

    result = helper.run(
        wait_for_drain=lambda timeout: events.append("drain") or True,
        request_supervisor_restart=lambda value: events.append("request") or True,
        wait_for_startup=lambda value, timeout: events.append("startup") or True,
    )

    assert result.phase is RestartPhase.STARTED
    assert events == ["drain", "request", "startup"]


def test_restart_helper_does_not_request_supervisor_after_failed_drain() -> None:
    intent = DetachedRestartIntent(1, "slot-next", "c" * 64, "launchd")
    helper = DetachedRestartHelper(intent)
    requested = []

    result = helper.run(
        wait_for_drain=lambda timeout: False,
        request_supervisor_restart=lambda value: requested.append(value) or True,
        wait_for_startup=lambda value, timeout: True,
    )

    assert result.phase is RestartPhase.FAILED
    assert requested == []
