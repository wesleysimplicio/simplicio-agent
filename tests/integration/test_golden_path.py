from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent.golden_path import GoldenPathHarness, build_fixture_mcp_call
from tools.simplicio_transport import FALLBACK_REASON_CLI_UNAVAILABLE


pytestmark = pytest.mark.integration


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "golden-path"


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "golden-path"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def _write_cli_wrapper(fixture_root: Path) -> Path:
    driver = (fixture_root / "fake_simplicio.py").resolve()
    if os.name == "nt":
        wrapper = (fixture_root / "fake-simplicio.cmd").resolve()
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "{driver}" %*\r\n',
            encoding="utf-8",
        )
        return wrapper
    wrapper = (fixture_root / "fake-simplicio").resolve()
    wrapper.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{driver}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return wrapper


def _runtime_cli_probe(repo: Path) -> dict:
    binary = shutil.which("simplicio")
    if binary is None:
        return {
            "available": False,
            "status": "unavailable",
            "command": "simplicio version --json",
        }
    try:
        result = subprocess.run(
            [binary, "version", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": True,
            "status": "failed",
            "command": "simplicio version --json",
            "error": type(exc).__name__,
        }
    probe = {
        "available": True,
        "status": "passed" if result.returncode == 0 else "failed",
        "command": "simplicio version --json",
        "returncode": result.returncode,
    }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        probe["schema"] = payload.get("schema")
        runtime = payload.get("runtime")
        if isinstance(runtime, dict):
            probe["runtime_version"] = runtime.get("version")
    return probe


def test_golden_path_cli_healthy_runs_real_cli_transport(tmp_path, monkeypatch):
    fixture_root = _copy_fixture(tmp_path)
    monkeypatch.setenv("GOLDEN_PATH_SCENARIO", str(fixture_root / "scenario.json"))
    harness = GoldenPathHarness.from_fixture(
        fixture_root,
        cli_bin=str(_write_cli_wrapper(fixture_root)),
    )

    result = harness.run(runtime_cli=_runtime_cli_probe(fixture_root / "workspace"))

    assert result.envelope.state is result.envelope.state.CLOSED
    assert result.envelope.lease == "lease-golden-path"
    assert result.envelope.write_set == (
        str((fixture_root / "workspace" / "state.txt").resolve()),
    )
    assert result.final_state == {"workspace/state.txt": "status=ready\nversion=2\n"}
    assert result.requery["matches_expected"] is True
    assert result.transport_health["cli_calls"] == 5
    assert result.transport_health["mcp_calls"] == 0
    assert result.transport_health["fallbacks"] == 0
    assert result.transport_receipts["mutation"].transport == "cli"
    assert result.protocol_sequences == tuple(range(1, 10))
    assert result.envelope.evidence_refs
    assert Path(result.evidence_path).is_file()
    evidence = json.loads(Path(result.evidence_path).read_text(encoding="utf-8"))
    assert evidence["proof"]["clean_machine_proof"] == "not_claimed"
    assert evidence["task"]["states"] == [
        "received",
        "oriented",
        "planned",
        "claimed",
        "executing",
        "validating",
        "evidence_ready",
        "delivered",
        "closed",
    ]
    assert Path(result.receipt_files["lease"]).is_file()
    assert Path(result.receipt_files["mutation"]).is_file()
    assert Path(result.receipt_files["validation"]).is_file()
    assert Path(result.receipt_files["evidence"]).is_file()
    assert Path(result.receipt_files["delivery"]).is_file()
    assert (fixture_root / "workspace" / "state.txt").read_text(encoding="utf-8") == (
        "status=ready\nversion=2\n"
    )


def test_golden_path_falls_back_when_cli_is_unavailable(tmp_path, monkeypatch):
    fixture_root = _copy_fixture(tmp_path)
    monkeypatch.setenv("GOLDEN_PATH_SCENARIO", str(fixture_root / "scenario.json"))
    scenario = GoldenPathHarness.from_fixture(fixture_root).scenario
    harness = GoldenPathHarness.from_fixture(
        fixture_root,
        cli_bin=str(fixture_root / "missing-simplicio"),
        mcp_call=build_fixture_mcp_call(scenario),
    )

    result = harness.run(runtime_cli={"available": False, "status": "not-run"})

    assert result.envelope.state is result.envelope.state.CLOSED
    assert result.transport_health["cli_calls"] == 0
    assert result.transport_health["mcp_calls"] == 5
    assert result.transport_health["fallbacks"] == 5
    assert result.transport_receipts["lease"].transport == "mcp"
    assert result.transport_receipts["delivery"].fallback_reason == (
        FALLBACK_REASON_CLI_UNAVAILABLE
    )
    assert result.protocol_sequences == tuple(range(1, 10))
    assert all(
        event["reason"] == FALLBACK_REASON_CLI_UNAVAILABLE
        for event in result.fallback_events
    )
    assert result.requery["matches_expected"] is True
