from __future__ import annotations

import copy
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent.golden_path import (
    GoldenPathHarness,
    GoldenPathScenario,
    build_fixture_mcp_call,
)
from tools.golden_path import (
    GoldenPathReceiptError,
    build_request_delivery_receipt,
    verify_request_delivery_receipt,
    write_request_delivery_receipt,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "golden-path"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _copy_fixture(tmp_path: Path) -> Path:
    fixture_root = tmp_path / "golden-path"
    shutil.copytree(FIXTURE_ROOT, fixture_root)
    return fixture_root


def _write_cli_wrapper(fixture_root: Path) -> Path:
    driver = (fixture_root / "fake_simplicio.py").resolve()
    if os.name == "nt":
        cli = fixture_root / "fake-simplicio.cmd"
        cli.write_text(
            f'@echo off\r\n"{sys.executable}" "{driver}" %*\r\n',
            encoding="utf-8",
        )
        return cli
    cli = fixture_root / "fake-simplicio"
    cli.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{driver}" "$@"\n',
        encoding="utf-8",
    )
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    return cli


def _fixture_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixture_root = _copy_fixture(tmp_path)
    monkeypatch.setenv("GOLDEN_PATH_SCENARIO", str(fixture_root / "scenario.json"))
    cli = _write_cli_wrapper(fixture_root)
    scenario = GoldenPathScenario.from_path(fixture_root)
    return GoldenPathHarness.from_fixture(
        fixture_root,
        cli_bin=str(cli),
        mcp_call=build_fixture_mcp_call(scenario),
    ).run()


def test_receipt_is_stable_and_explicitly_fixture_scoped(tmp_path, monkeypatch):
    result = _fixture_run(tmp_path, monkeypatch)

    receipt = build_request_delivery_receipt(result)

    assert verify_request_delivery_receipt(receipt) is True
    assert receipt["proof"] == {
        "clean_machine_e2e": "not_claimed",
        "external_services": False,
        "scope": "fixture_only",
    }
    assert receipt["request"]["scope"] == "issue-211"
    assert receipt["lifecycle"]["state"] == "closed"
    assert receipt["mutation"]["requery_matches_expected"] is True
    assert receipt["delivery"]["accepted"] is True
    assert build_request_delivery_receipt(result) == receipt


def test_receipt_writer_round_trips_and_tampering_is_rejected(tmp_path, monkeypatch):
    result = _fixture_run(tmp_path, monkeypatch)
    path = tmp_path / "receipt.json"

    receipt = write_request_delivery_receipt(result, path)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted == receipt
    assert verify_request_delivery_receipt(persisted) is True

    tampered = copy.deepcopy(persisted)
    tampered["delivery"]["accepted"] = False
    with pytest.raises(GoldenPathReceiptError, match="receipt_sha256"):
        verify_request_delivery_receipt(tampered)


def test_receipt_build_fails_closed_when_evidence_artifact_is_missing(
    tmp_path, monkeypatch
):
    result = _fixture_run(tmp_path, monkeypatch)
    Path(result.receipt_files["evidence"]).unlink()

    with pytest.raises(
        GoldenPathReceiptError,
        match="evidence receipt artifact is missing",
    ):
        build_request_delivery_receipt(result)


def test_module_executes_request_to_delivery_and_writes_verified_receipt(tmp_path):
    fixture_root = _copy_fixture(tmp_path)
    cli = _write_cli_wrapper(fixture_root)
    output = tmp_path / "artifacts" / "request-delivery.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.golden_path",
            "--fixture",
            str(fixture_root),
            "--cli-bin",
            str(cli),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "MEASURED"
    assert report["lifecycle_state"] == "closed"
    assert report["receipt_sha256"] == receipt["receipt_sha256"]
    assert verify_request_delivery_receipt(receipt) is True
