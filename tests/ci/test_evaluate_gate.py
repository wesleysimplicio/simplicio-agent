"""Offline contract tests for the issue #349 aggregate gate evaluator."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci.evaluate_gate import evaluate, main


def test_all_success_is_pass() -> None:
    receipt = evaluate({"tests": {"result": "success"}, "lint": {"result": "success"}})
    assert receipt["status"] == "PASS"
    assert all(item["status"] == "PASS" for item in receipt["results"].values())


def test_intentional_skip_is_visible_as_unverified() -> None:
    receipt = evaluate({"tests": {"result": "skipped"}})
    assert receipt["status"] == "UNVERIFIED"
    assert receipt["results"]["tests"]["status"] == "UNVERIFIED"


def test_non_success_states_are_blocking() -> None:
    for result in ("failure", "cancelled", "timed_out", "action_required"):
        receipt = evaluate({"gate": {"result": result}})
        assert receipt["status"] == "FAIL"
        assert receipt["results"]["gate"]["status"] == "FAIL"


def test_malformed_result_is_unverified_and_invalid_json_fails(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    assert main(["--needs-json", json.dumps({"gate": {}}), "--receipt", str(receipt_path)]) == 0
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == "UNVERIFIED"
    invalid_path = tmp_path / "invalid.json"
    assert main(["--needs-json", "not-json", "--receipt", str(invalid_path)]) == 1
    assert json.loads(invalid_path.read_text(encoding="utf-8"))["status"] == "UNVERIFIED"
