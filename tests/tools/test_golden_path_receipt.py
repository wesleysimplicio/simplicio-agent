from __future__ import annotations

import copy
import json
import os
import shutil
import stat
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


def _fixture_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixture_root = tmp_path / "golden-path"
    shutil.copytree(FIXTURE_ROOT, fixture_root)
    monkeypatch.setenv("GOLDEN_PATH_SCENARIO", str(fixture_root / "scenario.json"))
    driver = (fixture_root / "fake_simplicio.py").resolve()
    if os.name == "nt":
        cli = fixture_root / "fake-simplicio.cmd"
        cli.write_text(
            f'@echo off\r\n"{sys.executable}" "{driver}" %*\r\n',
            encoding="utf-8",
        )
    else:
        cli = fixture_root / "fake-simplicio"
        cli.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{driver}" "$@"\n',
            encoding="utf-8",
        )
        cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
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
