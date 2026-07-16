from __future__ import annotations

import json

from tools.release_handoff import audit_payload, main


def test_audit_payload_is_blocked_without_clean_machine_proof() -> None:
    receipt = audit_payload({"evidence": {}})
    assert receipt["readiness"] == "blocked"
    assert receipt["clean_machine_release_proof"] == "not_proven"
    assert any("clean-machine release proof" in item for item in receipt["blockers"])


def test_cli_writes_deterministic_machine_receipt(tmp_path) -> None:
    source = tmp_path / "evidence.json"
    output = tmp_path / "out" / "handoff.json"
    source.write_text(json.dumps({"evidence": {}}), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output)]) == 0
    first = output.read_text(encoding="utf-8")
    assert json.loads(first)["issue_number"] == 144
    assert first == output.read_text(encoding="utf-8")


def test_cli_rejects_malformed_evidence(tmp_path) -> None:
    source = tmp_path / "evidence.json"
    output = tmp_path / "handoff.json"
    source.write_text(json.dumps({"evidence": {"install": []}}), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output)]) == 2
    assert not output.exists()
