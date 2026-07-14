"""Focused contract tests for the deterministic perf manifest (issue #220)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.perf_integration_manifest import (
    REPO_ROOT,
    SCHEMA,
    STAGES,
    _exercise_fast_json,
    generate_manifest,
    main,
    validate_manifest,
)

MANIFEST = REPO_ROOT / "tools" / "perf_integration_manifest.py"
FIXTURE = (
    REPO_ROOT / "fixtures" / "bench" / "perf" / "perf-integration-manifest.v1.json"
)


def test_manifest_is_deterministic_and_has_v1_provenance() -> None:
    first = generate_manifest(REPO_ROOT)
    second = generate_manifest(REPO_ROOT)
    assert first == second
    assert first["schema"] == SCHEMA
    assert first["version"] == 1
    assert first["summary"]["ok"] is True
    for axis in first["axes"]:
        assert set(axis["stage_results"]) == set(STAGES)
        assert set(axis["source_sha256"]) == set(axis["source"])
        assert axis["call_sites"]
        assert axis["config"]
        assert axis["fallback"]["available"] is True
        # The compact legacy view and the v1 classification must agree.
        for stage in STAGES:
            assert axis["stages"][stage] == axis["stage_results"][stage]["ok"]


def test_every_stage_is_classified_after_a_missing_source(tmp_path: Path) -> None:
    document = generate_manifest(tmp_path)
    for axis in document["axes"]:
        assert set(axis["stage_results"]) == set(STAGES)
        assert all("status" in axis["stage_results"][stage] for stage in STAGES)
    assert document["summary"]["ok"] is False


def test_validator_rejects_bad_schema_and_source_hash() -> None:
    document = generate_manifest(REPO_ROOT)
    document["schema"] = "wrong/v0"
    document["axes"][0]["source_sha256"][document["axes"][0]["source"][0]] = "0" * 64
    errors = validate_manifest(document, REPO_ROOT)
    assert any("schema" in error for error in errors)
    assert any("source_sha256 mismatch" in error for error in errors)


def test_validator_rejects_inconsistent_stage_receipts_and_summary() -> None:
    document = generate_manifest(REPO_ROOT)
    axis = document["axes"][0]
    axis["stage_results"]["PRESENT"]["status"] = "fail"
    axis["stage_results"]["PRESENT"]["ok"] = True
    axis["stage_status"]["PRESENT"] = "pass"
    axis["stages"]["PRESENT"] = True
    axis["ok"] = True
    document["summary"]["failed"] = 1
    document["summary"]["ok"] = False
    errors = validate_manifest(document)
    assert errors == sorted(set(errors))
    assert any("status receipt disagrees" in error for error in errors)
    assert any(".ok disagrees with stage results" in error for error in errors)
    assert any("summary.failed disagrees" in error for error in errors)


def test_validator_rejects_malformed_source_receipts_without_crashing() -> None:
    document = generate_manifest(REPO_ROOT)
    axis = document["axes"][0]
    axis["source"] = [{"not": "a path"}]
    axis["source_sha256"] = {}
    errors = validate_manifest(document)
    assert any("non-canonical path" in error for error in errors)
    assert any("source_sha256 must hash every source path" in error for error in errors)


def test_fast_json_invocation_receipt_exercises_selected_backend() -> None:
    ok, reason = _exercise_fast_json(REPO_ROOT)
    assert ok is True
    assert "backend=" in reason
    assert "encode=called" in reason
    assert "decode=called" in reason
    assert "round_trip=pass" in reason


def test_fixture_is_a_valid_committed_v1_document() -> None:
    assert FIXTURE.is_file()
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert validate_manifest(document, REPO_ROOT) == []
    assert document == generate_manifest(REPO_ROOT)


def test_cli_generate_and_validate(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    assert main(["--generate", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == SCHEMA
    assert main(["--validate", str(output)]) == 0


def test_cli_json_reports_uvloop_regression(tmp_path: Path) -> None:
    """The Linux fast path fails independently when uvloop is blocked."""
    if sys.platform == "win32":
        pytest.skip("uvloop is intentionally not applicable on Windows")
    shim = tmp_path / "block_uvloop.py"
    shim.write_text(
        "import sys, importlib.abc\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name == 'uvloop' or name.startswith('uvloop.'):\n"
        "            raise ImportError('blocked for test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Block())\n",
        encoding="utf-8",
    )
    runner = (
        "import runpy; "
        f"exec(compile(open({str(shim)!r}).read(), {str(shim)!r}, 'exec')); "
        f"runpy.run_path({str(MANIFEST)!r}, run_name='__main__')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", runner, "--repo", str(REPO_ROOT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode != 0
    uvloop = next(
        axis for axis in json.loads(proc.stdout)["axes"] if axis["name"] == "uvloop"
    )
    assert uvloop["stage_results"]["INSTALLED"]["status"] == "fail"
    assert uvloop["stages"]["INSTALLED"] is False
