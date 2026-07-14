from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.release_gate import (
    SCAN_CONTRACT_SCHEMA,
    SCAN_RECEIPT_SCHEMA,
    SURFACE_SCAN_SCHEMA,
    build_scan_contract,
    build_scan_receipt,
    scan_source_package_runtime,
    validate_scan_contract,
    validate_scan_receipt,
)
from tools.release_gate_scan import main
from tools.release_manifest import digest_document


ROOT = Path(__file__).resolve().parents[2]
IDENTITY_MANIFEST = {
    "schema": "simplicio.identity-legacy-manifest/v1",
    "version": 1,
    "entries": [],
}


def _manifest() -> dict[str, object]:
    return json.loads(
        (ROOT / "fixtures" / "release-manifest" / "release-manifest.v1.json").read_text(
            encoding="utf-8"
        )
    )


def _contract() -> dict[str, object]:
    return build_scan_contract(
        scenario="clean-install",
        manifest=_manifest(),
        surfaces={
            "source": ["src"],
            "package": ["package.bin"],
            "runtime": ["runtime.bin"],
        },
        receipts=["receipts/scan.json"],
    )


def test_scan_contract_is_bounded_and_uses_existing_manifest_digest() -> None:
    contract = _contract()

    assert contract["schema"] == SCAN_CONTRACT_SCHEMA
    assert contract["manifest_digest"] == _manifest()["manifest_digest"]
    assert contract["proof"] == {
        "clean_machine_e2e": "not_claimed",
        "external_services": False,
        "mutates_release": False,
        "publishes_artifact": False,
    }
    assert validate_scan_contract(contract, manifest=_manifest()) == []


@pytest.mark.parametrize("scenario", ("clean-install", "upgrade", "rollback"))
def test_all_release_scenarios_have_the_same_bounded_contract(scenario: str) -> None:
    contract = build_scan_contract(
        scenario=scenario,
        manifest=_manifest(),
        surfaces={kind: [f"{kind}.bin"] for kind in ("source", "package", "runtime")},
        receipts=[f"receipts/{scenario}.json"],
    )
    assert validate_scan_contract(contract, manifest=_manifest()) == []


def test_committed_scan_contract_fixture_is_valid() -> None:
    fixture = json.loads(
        (
            ROOT / "fixtures" / "release-gate" / "release-scan-contract.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert validate_scan_contract(fixture, manifest=_manifest()) == []
    assert (
        main([
            "validate-contract",
            str(ROOT / "fixtures" / "release-gate" / "release-scan-contract.v1.json"),
            "--manifest",
            str(ROOT / "fixtures" / "release-manifest" / "release-manifest.v1.json"),
        ])
        == 0
    )


def test_surface_scans_are_read_only_and_detect_legacy_source(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.py").write_text("name = 'hermes-agent'\n", encoding="utf-8")
    (tmp_path / "package.bin").write_bytes(b"fixture-package")
    (tmp_path / "runtime.bin").write_bytes(b"fixture-runtime")

    scans = scan_source_package_runtime(
        tmp_path,
        paths={
            "source": ["src"],
            "package": ["package.bin"],
            "runtime": ["runtime.bin"],
        },
        identity_manifest=IDENTITY_MANIFEST,
        today="2026-07-14",
    )

    assert set(scans) == {"source", "package", "runtime"}
    assert scans["source"]["schema"] == SURFACE_SCAN_SCHEMA
    assert scans["source"]["ok"] is False
    assert scans["source"]["blocking_count"] == 1
    assert scans["package"]["files"][0]["digest"].startswith("sha256:")
    assert (source / "main.py").exists()


def test_scan_receipt_binds_contract_and_rejects_tampering(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.py").write_text("name = 'simplicio-agent'\n", encoding="utf-8")
    (tmp_path / "package.bin").write_bytes(b"fixture-package")
    (tmp_path / "runtime.bin").write_bytes(b"fixture-runtime")
    contract = _contract()
    scans = scan_source_package_runtime(
        tmp_path,
        paths={
            "source": ["src"],
            "package": ["package.bin"],
            "runtime": ["runtime.bin"],
        },
        identity_manifest=IDENTITY_MANIFEST,
    )

    receipt = build_scan_receipt(
        contract,
        scans=scans,
        status="pass",
        receipts=["receipts/source.json", "receipts/package.json"],
    )
    assert receipt["schema"] == SCAN_RECEIPT_SCHEMA
    assert validate_scan_receipt(receipt, contract=contract) == []
    assert receipt["receipt_digest"] == digest_document({
        key: value for key, value in receipt.items() if key != "receipt_digest"
    })

    tampered = copy.deepcopy(receipt)
    tampered["surfaces"]["runtime"]["files"][0]["size"] += 1  # type: ignore[index]
    assert (
        "surfaces.runtime.scan_digest does not match contents"
        in validate_scan_receipt(tampered, contract=contract)
    )
    assert "receipt_digest does not match canonical payload" in validate_scan_receipt(
        tampered, contract=contract
    )


def test_receipt_requires_all_surfaces_and_does_not_accept_not_attempted() -> None:
    contract = _contract()
    with pytest.raises(ValueError, match="scans missing required surfaces"):
        build_scan_receipt(
            contract,
            scans={},
            status="not_attempted",
            receipts=["receipts/scan.json"],
        )

    invalid = copy.deepcopy(contract)
    invalid["proof"]["publishes_artifact"] = True  # type: ignore[index]
    assert "proof.publishes_artifact must be false" in validate_scan_contract(invalid)


def test_surface_path_cannot_escape_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-release-gate-fixture.txt"
    outside.write_text("fixture", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="escapes root"):
            scan_source_package_runtime(
                tmp_path,
                paths={
                    kind: ["../outside-release-gate-fixture.txt"]
                    for kind in ("source", "package", "runtime")
                },
            )
    finally:
        outside.unlink(missing_ok=True)
