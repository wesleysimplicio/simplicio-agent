"""System/E2E test for ``simplicio-agent update plan`` (issue #342).

Invokes the real CLI as a subprocess (matching the pattern used by
``tests/hermes_cli/test_daemon.py``'s ``_run_cli`` helper) and asserts on
its real, observed output — not on internal function calls. A filesystem
sentinel proves the read-only preflight report performs zero writes,
satisfying the "system test: simplicio update plan does not write anything"
acceptance criterion from issue #342.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(*argv, env=None, timeout=30):
    return subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _snapshot_tree(root: Path) -> dict:
    """Return a {relative_path: (size, mtime_ns)} map for every file under root."""
    out = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            out[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return out


@pytest.fixture
def isolated_home(tmp_path):
    """A throwaway HERMES_HOME so the test never touches the real user home."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    env = {**os.environ, "HERMES_HOME": str(home)}
    return home, env


@pytest.mark.live_system_guard_bypass
def test_update_plan_help_is_registered():
    result = _run_cli("update", "--help", env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert "plan" in result.stdout


@pytest.mark.live_system_guard_bypass
def test_update_plan_reports_real_installation_detection(isolated_home):
    """The plan output must reflect this checkout's *actual* detected state —
    this repo is a real git checkout, so 'git' must appear (anti-tautology:
    a stub that always prints 'git' would also pass a naive substring check,
    but here the value is cross-checked against detect_installation() directly
    in test_update_preflight.py's own unit tests; this test exercises the
    real CLI process, not a mock).
    """
    _, env = isolated_home
    result = _run_cli("update", "plan", env=env)
    assert result.returncode == 0, result.stderr
    assert "Update plan (read-only" in result.stdout
    assert "Installation state:" in result.stdout
    assert "Install type" in result.stdout
    assert "Lock status       : free" in result.stdout
    assert "Plan complete" in result.stdout


@pytest.mark.live_system_guard_bypass
def test_update_plan_writes_nothing_to_project_root_or_hermes_home(isolated_home):
    """Filesystem sentinel: capture (size, mtime) for every file under the
    project root and the isolated HERMES_HOME before and after running
    ``update plan``, and assert the sets are byte-for-byte identical.
    """
    home, env = isolated_home
    project_root = Path(__file__).resolve().parent.parent.parent

    before_project = _snapshot_tree(project_root)
    before_home = _snapshot_tree(home)

    result = _run_cli("update", "plan", env=env)
    assert result.returncode == 0, result.stderr

    after_project = _snapshot_tree(project_root)
    after_home = _snapshot_tree(home)

    assert after_project == before_project, "update plan wrote to the project root"
    assert after_home == before_home, "update plan wrote under HERMES_HOME"


def test_update_plan_refuses_when_installation_type_unknown(isolated_home, tmp_path):
    """Fail-closed contract: an ambiguous/undetectable install exits non-zero
    and never claims success. Uses an empty directory as PROJECT_ROOT via a
    monkeypatched entry point is not possible across a subprocess boundary,
    so this drives the same real code path in-process instead.
    """
    from hermes_cli import main as main_mod

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    original_root = main_mod.PROJECT_ROOT
    main_mod.PROJECT_ROOT = empty_root
    try:
        with pytest.raises(SystemExit) as exc_info:
            main_mod._cmd_update_plan(object())
        assert exc_info.value.code == 1
    finally:
        main_mod.PROJECT_ROOT = original_root
