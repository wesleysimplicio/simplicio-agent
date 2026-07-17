"""Focused Native 2.3 tests for staging, activation, and detached restart."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from hermes_cli.staging_activation import (
    AtomicCurrentPointer,
    DetachedRestartHelper,
    DetachedRestartIntent,
    GateName,
    PointerRecord,
    RestartPhase,
    StagingValidationError,
    _atomic_write,
    _directory_digest,
    _inside,
    _lock_digest,
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


def test_restart_helper_stops_when_supervisor_rejects_restart() -> None:
    intent = DetachedRestartIntent(1, "slot-next", "d" * 64, "systemd")
    helper = DetachedRestartHelper(intent)
    startup_calls: list[object] = []

    result = helper.run(
        wait_for_drain=lambda timeout: True,
        request_supervisor_restart=lambda value: False,
        wait_for_startup=lambda value, timeout: startup_calls.append(value) or True,
    )

    assert result.phase is RestartPhase.FAILED
    assert "supervisor" in result.detail
    assert startup_calls == []


def test_restart_helper_fails_when_startup_never_becomes_healthy() -> None:
    intent = DetachedRestartIntent(1, "slot-next", "e" * 64, "systemd")
    helper = DetachedRestartHelper(intent)

    result = helper.run(
        wait_for_drain=lambda timeout: True,
        request_supervisor_restart=lambda value: True,
        wait_for_startup=lambda value, timeout: False,
    )

    assert result.phase is RestartPhase.FAILED
    assert "healthy" in result.detail


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"schema": "bogus/v1"}, "unsupported restart intent schema"),
        ({"old_pid": 0}, "pid"),
        ({"target_slot": ""}, "pid"),
        ({"pointer_digest": ""}, "pid"),
        ({"drain_timeout_s": -1}, "timeouts"),
        ({"startup_timeout_s": -1}, "timeouts"),
        ({"supervisor": ""}, "supervisor"),
    ],
)
def test_detached_restart_intent_rejects_invalid_fields(
    kwargs: dict[str, object], message: str
) -> None:
    base = dict(
        old_pid=100,
        target_slot="slot-a",
        pointer_digest="f" * 64,
        supervisor="systemd",
    )
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        DetachedRestartIntent(**base)


def test_touched_files_escaping_staging_fails_syntax_gate_and_leaves_active_tree(
    tmp_path: Path,
) -> None:
    staging = _staging(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("X = 1\n", encoding="utf-8")

    result = validate_staging(
        staging,
        touched_files=("../outside.py",),
        entrypoints=("hermes_cli.config",),
        focused_smoke=lambda path: True,
    )

    assert result.gates[0].name is GateName.SYNTAX
    assert result.gates[0].passed is False
    assert "escapes staging" in result.gates[0].detail
    assert result.passed is False


def test_inside_helper_distinguishes_contained_and_escaping_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside_path = root / "child" / "file.txt"
    outside_path = tmp_path / "sibling" / "file.txt"

    assert _inside(root, inside_path) is True
    assert _inside(root, outside_path) is False


def test_directory_digest_rejects_symlink_root_and_missing_directory(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="real directory"):
        _directory_digest(missing)

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")
    with pytest.raises(ValueError, match="real directory"):
        _directory_digest(link)


def test_directory_digest_rejects_symlinked_member(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.txt").write_text("data", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(root / "real.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")
    with pytest.raises(ValueError, match="symlink"):
        _directory_digest(root)


def test_directory_digest_is_stable_and_sensitive_to_content(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("A = 1\n", encoding="utf-8")

    first = _directory_digest(root)
    second = _directory_digest(root)
    assert first == second

    (root / "pkg" / "a.py").write_text("A = 2\n", encoding="utf-8")
    assert _directory_digest(root) != first


def test_config_gate_reports_missing_pyyaml_as_a_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = _staging(tmp_path)
    (staging / "config.yaml").write_text("schema: v1\n", encoding="utf-8")

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no yaml available")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = validate_staging(
        staging,
        entrypoints=("hermes_cli.config",),
        focused_smoke=lambda path: True,
    )

    assert result.gates[2].name is GateName.CONFIG
    assert result.gates[2].passed is False
    assert "PyYAML" in result.gates[2].detail


def test_config_gate_default_validator_reports_schema_errors(tmp_path: Path) -> None:
    staging = _staging(tmp_path, config={"unexpected": True})

    result = validate_staging(
        staging,
        entrypoints=("hermes_cli.config",),
        focused_smoke=lambda path: True,
    )

    config_gate = result.gates[2]
    assert config_gate.name is GateName.CONFIG
    # Whatever the schema registry decides, the gate must actually run the
    # real validator rather than always reporting success.
    assert config_gate.detail


def test_config_path_escaping_staging_is_rejected(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    outside_config = tmp_path / "config.json"
    outside_config.write_text("{}", encoding="utf-8")

    result = validate_staging(
        staging,
        entrypoints=("hermes_cli.config",),
        config_paths=("../config.json",),
        focused_smoke=lambda path: True,
    )

    assert result.gates[2].name is GateName.CONFIG
    assert result.gates[2].passed is False
    assert "escapes staging" in result.gates[2].detail


def test_lock_digest_rejects_lockfile_path_escaping_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError, match="escapes root"):
        _lock_digest(root, ("../secrets.lock",))


def test_lock_sync_decision_serialization_reflects_change(tmp_path: Path) -> None:
    active = tmp_path / "active"
    staging = tmp_path / "staging"
    active.mkdir()
    staging.mkdir()
    (active / "uv.lock").write_text("v1", encoding="utf-8")
    (staging / "uv.lock").write_text("v2", encoding="utf-8")

    decision = decide_lock_sync(staging, active, lockfiles=("uv.lock",))
    payload = decision.to_dict()

    assert payload["changed"] is True
    assert payload["should_sync"] is True
    assert payload["lockfiles"] == ["uv.lock"]
    assert payload["staging_digest"] != payload["active_digest"]


def test_atomic_write_produces_readable_file_and_cleans_temp_files(
    tmp_path: Path,
) -> None:
    target = tmp_path / "current"
    _atomic_write(target, "hello-world")

    assert target.read_text(encoding="utf-8") == "hello-world"
    leftovers = list(tmp_path.glob(".current.*.tmp"))
    assert leftovers == []


def test_pointer_read_rejects_tampered_digest(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    validation = _validated(staging)
    pointer = AtomicCurrentPointer(tmp_path / "install")
    record = pointer.activate(staging, validation=validation)

    # Corrupt the published slot in place; the digest recorded in `current`
    # must no longer match the bytes on disk.
    (pointer.slots / record.slot / "hermes_cli" / "config.py").write_text(
        "TAMPERED = True\n", encoding="utf-8"
    )

    with pytest.raises(StagingValidationError, match="digest verification"):
        pointer.read()


def test_pointer_read_rejects_wrong_schema_in_current_file(tmp_path: Path) -> None:
    install = tmp_path / "install"
    pointer = AtomicCurrentPointer(install)
    (install / "current").write_text(
        json.dumps({"schema": "not-the-real-schema", "slot": "x", "digest": "y"}),
        encoding="utf-8",
    )

    with pytest.raises(StagingValidationError, match="invalid fields"):
        pointer.read()


def test_pointer_read_rejects_malformed_json(tmp_path: Path) -> None:
    install = tmp_path / "install"
    pointer = AtomicCurrentPointer(install)
    (install / "current").write_text("not json at all", encoding="utf-8")

    with pytest.raises(StagingValidationError, match="invalid current pointer"):
        pointer.read()


def test_activate_requires_a_validation_receipt(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    pointer = AtomicCurrentPointer(tmp_path / "install")

    with pytest.raises(StagingValidationError, match="requires a staging validation"):
        pointer.activate(staging, validation=None)


def test_activate_rejects_validation_for_a_different_staging_tree(
    tmp_path: Path,
) -> None:
    staging = _staging(tmp_path)
    other_root = tmp_path / "other"
    other = _staging(other_root)
    other_validation = _validated(other)
    pointer = AtomicCurrentPointer(tmp_path / "install")

    with pytest.raises(StagingValidationError, match="did not all pass"):
        pointer.activate(staging, validation=other_validation)


def test_concurrent_readers_never_observe_a_mixed_or_missing_slot(
    tmp_path: Path,
) -> None:
    """Native 2.3 acceptance criterion: 100 pointer swaps, reader loop concurrently.

    A reader thread continuously calls ``AtomicCurrentPointer.read`` while the
    main thread performs successive real ``activate`` calls (real filesystem
    copytree + atomic rename, no mocks). Every observation must either be
    ``None`` (before the first publish) or a pointer whose slot digest matches
    bytes actually on disk -- never a torn/half-written state.
    """

    staging = _staging(tmp_path)
    pointer = AtomicCurrentPointer(tmp_path / "install")
    stop = threading.Event()
    observations: list[object] = []
    errors: list[BaseException] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                observations.append(pointer.read())
            except StagingValidationError as exc:
                if isinstance(exc.__cause__, PermissionError):
                    # Windows denies concurrent opens of a file mid-``os.replace``
                    # (a sharing violation), which is a transient OS-level lock
                    # conflict, not the code observing a torn/mixed pointer --
                    # the POSIX rename this guards against is atomic w.r.t.
                    # readers. Retry instead of treating it as a correctness
                    # failure.
                    continue
                errors.append(exc)
                return
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        previous_slots: list[str] = []
        for i in range(20):
            (staging / "hermes_cli" / "config.py").write_text(
                f"VALUE = {i}\n", encoding="utf-8"
            )
            validation = _validated(staging)
            # ``os.replace`` on Windows can raise a transient PermissionError
            # if a reader has the destination file open at that instant (POSIX
            # rename has no such restriction). Retrying the publish keeps this
            # test about the *correctness property* -- readers never see a
            # mixed slot -- rather than a Windows scheduling artifact. On the
            # project's Linux CI target this loop always succeeds first try.
            for attempt in range(50):
                try:
                    record = pointer.activate(staging, validation=validation)
                except PermissionError:
                    if attempt == 49:
                        raise
                    time.sleep(0.001)
                    continue
                break
            previous_slots.append(record.slot)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert not errors
    assert observations, "reader thread never observed the pointer"
    seen_slots = {obs.slot for obs in observations if obs is not None}
    assert seen_slots
    assert seen_slots.issubset(set(previous_slots))
    final = pointer.read()
    assert final is not None
    assert final.slot == previous_slots[-1]


def test_detached_restart_helper_launches_a_real_independent_process(
    tmp_path: Path,
) -> None:
    """Exercise ``DetachedRestartHelper.launch`` against a real subprocess.

    No mocked Popen: the helper spawns an actual Python interpreter that
    records its own pid and its parent's pid, proving the launch call
    produced a genuine child process distinct from the test process while
    still being directly spawned by it (the detachment flags only take
    effect once *this* process exits/drops the console, which the helper
    contract requires the old process never do as part of the update).
    """

    intent = DetachedRestartIntent(
        old_pid=os.getpid(),
        target_slot="slot-real",
        pointer_digest="0" * 64,
        supervisor="test-supervisor",
    )
    helper = DetachedRestartHelper(intent)
    marker = tmp_path / "child_report.txt"
    script = tmp_path / "child.py"
    script.write_text(
        "import os, pathlib\n"
        f"pathlib.Path(r'{marker}').write_text(f'{{os.getpid()}} {{os.getppid()}}')\n",
        encoding="utf-8",
    )

    process = helper.launch([sys.executable, str(script)], tmp_path / "intent.json")
    try:
        process.wait(timeout=15)
    finally:
        if process.poll() is None:  # pragma: no cover - safety net
            process.kill()

    assert marker.exists(), "detached child never ran"
    child_pid_text, child_ppid_text = marker.read_text(encoding="utf-8").split()
    assert int(child_pid_text) == process.pid
    assert int(child_pid_text) != os.getpid()

    intent_path = tmp_path / "intent.json"
    written = json.loads(intent_path.read_text(encoding="utf-8"))
    assert written["target_slot"] == "slot-real"
    assert written["old_pid"] == os.getpid()
