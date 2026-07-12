from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools" / "build_bundle.sh"
MANIFEST = ROOT / "tools" / "bundle_manifest.py"


def make_release(home: Path, version: str, payload: str) -> Path:
    release = home / "releases" / version
    (release / "venv" / "bin").mkdir(parents=True)
    (release / "venv" / "bin" / "python").write_text("#!/bin/sh\nexit 0\n")
    (release / "venv" / "bin" / "python").chmod(0o755)
    (release / "payload.txt").write_text(payload)
    subprocess.run(
        [
            "python3",
            str(MANIFEST),
            "create",
            str(release),
            "--version",
            version,
            "--source-commit",
            "fixture",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return release


def run_builder(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SIMPLICIO_AGENT_HOME"] = str(home)
    env["SIMPLICIO_AGENT_REPO"] = str(ROOT)
    return subprocess.run(
        ["bash", str(BUILDER), *args],
        env=env,
        capture_output=True,
        text=True,
    )


def test_clean_temp_bundle_verifies_and_detects_tamper(tmp_path: Path) -> None:
    release = make_release(tmp_path, "fixture-a", "stable")
    verified = run_builder(tmp_path, "--verify", str(release))
    assert verified.returncode == 0, verified.stderr
    assert "verified: fixture-a" in verified.stdout

    (release / "payload.txt").write_text("tampered")
    rejected = run_builder(tmp_path, "--verify", str(release))
    assert rejected.returncode != 0
    assert "verification failed" in rejected.stderr


def test_promotion_and_failed_rollback_keep_previous_current(tmp_path: Path) -> None:
    old = make_release(tmp_path, "old", "old")
    new = make_release(tmp_path, "new", "new")
    current = tmp_path / "current"
    current.symlink_to(old)

    promoted = run_builder(tmp_path, "--rollback", "new")
    assert promoted.returncode == 0, promoted.stderr
    assert current.resolve() == new.resolve()
    assert (tmp_path / ".active_bundle").read_text().strip() == "new"

    (old / "payload.txt").write_text("broken")
    failed = run_builder(tmp_path, "--rollback", "old")
    assert failed.returncode != 0
    assert current.resolve() == new.resolve(), failed.stderr

    manifest = json.loads((new / "manifests" / "bundle.json").read_text())
    assert manifest["signature"]["status"] == "unsigned"
    assert manifest["signature"]["verification"] == "sha256-only"
