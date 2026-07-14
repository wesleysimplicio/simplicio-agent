"""Executable integration receipt for the prompt microkernel (#220)."""

from __future__ import annotations

import json

from tools.prompt_microkernel_integration_receipt import (
    REPO_ROOT,
    collect_receipt,
    main,
)


def test_receipt_measures_source_loaded_and_called() -> None:
    receipt = collect_receipt(REPO_ROOT)

    assert receipt["schema"] == "simplicio.perf-integration-receipt/v1"
    assert receipt["optimization"] == "prompt-microkernel"
    assert receipt["ok"] is True
    for stage in ("SOURCE", "LOADED", "CALLED"):
        assert receipt["stages"][stage]["status"] == "pass"
        assert receipt["stages"][stage]["claim"] == "MEASURED"
        assert receipt["stages"][stage]["evidence"]


def test_receipt_keeps_unproven_product_stages_unverified() -> None:
    receipt = collect_receipt(REPO_ROOT)

    for stage in ("PACKAGED", "DEFAULT", "E2E"):
        assert receipt["stages"][stage] == {
            "status": "unknown",
            "claim": "UNVERIFIED",
            "reason": "not measured by this bounded receipt",
        }


def test_cli_emits_the_receipt(capsys) -> None:
    assert main(["--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document == collect_receipt(REPO_ROOT)
