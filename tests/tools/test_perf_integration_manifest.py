"""Tests for the Hermes Turbo performance integration manifest (issue #220).

Asserts the *contract* of tools/perf_integration_manifest.py:

1. With the ``[fast]`` extra installed, every shipped performance axis must
   satisfy PRESENT -> SAME_SOURCE -> BUILT -> PACKAGED -> INSTALLED ->
   INVOKED -> E2E -> DEFAULT -> GATED. This is the executable proof the
   issue asks for.
2. The manifest must return a non-zero exit and flag the broken axis when
   an optimisation regresses (here: uvloop import forced to fail), so a
   silent regression cannot ship.
"""
from __future__ import annotations

import builtins
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "tools" / "perf_integration_manifest.py"

pytestmark = pytest.mark.skipif(
    not MANIFEST.exists(),
    reason="perf_integration_manifest.py not present in this checkout",
)


def _run_manifest(repo_arg: str, *, block_uvloop: bool = False) -> subprocess.CompletedProcess[str]:
    env = dict(__import__("os").environ)
    shim_path: str | None = None
    if block_uvloop:
        # Make uvloop unimportable inside the subprocess only, via a small
        # import shim prepended to the runner script.
        import tempfile
        fd, shim_path = tempfile.mkstemp(suffix=".py", prefix="perf_block_")
        with __import__("os").fdopen(fd, "w") as fh:
            fh.write(
                "import sys, importlib.abc\n"
                "class _B(importlib.abc.MetaPathFinder):\n"
                "    def find_spec(self, name, path, target=None):\n"
                "        if name == 'uvloop' or name.startswith('uvloop.'):\n"
                "            raise ImportError('blocked for test')\n"
                "        return None\n"
                "sys.meta_path.insert(0, _B())\n"
            )
        env["_PERF_TEST_SHIM"] = shim_path
        runner = (
            "import runpy, os; "
            f"shim=os.environ['_PERF_TEST_SHIM']; "
            f"exec(compile(open(shim).read(), shim, 'exec')); "
            f"runpy.run_path({str(MANIFEST)!r}, run_name='__main__')"
        )
    else:
        runner = f"import runpy; runpy.run_path({str(MANIFEST)!r}, run_name='__main__')"
    try:
        return subprocess.run(
            [sys.executable, "-c", runner, "--repo", repo_arg, "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        if shim_path is not None:
            try:
                __import__("os").unlink(shim_path)
            except OSError:
                pass


def test_manifest_passes_with_fast_extra_installed() -> None:
    """The real repo, with [fast] installed, must satisfy every axis."""
    proc = _run_manifest(str(REPO_ROOT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["axes"], "no axes reported"
    for axis in report["axes"]:
        assert axis["ok"], f"axis {axis['name']} failed: {axis['stages']}"


def test_manifest_fails_when_uvloop_regresses() -> None:
    """Blocking uvloop must make the uvloop axis fail and the run non-zero."""
    proc = _run_manifest(str(REPO_ROOT), block_uvloop=True)
    assert proc.returncode != 0, "manifest must fail when uvloop is unavailable"
    report = json.loads(proc.stdout)
    uvloop_axis = next(a for a in report["axes"] if a["name"] == "uvloop")
    assert not uvloop_axis["ok"]
    assert uvloop_axis["stages"]["INSTALLED"] is False
