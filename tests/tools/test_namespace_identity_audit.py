import tarfile
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

from tools.namespace_identity_audit import (
    INVENTORY_SCHEMA,
    audit,
    build_receipt,
    scan_build,
    scan_runtime,
    scan_source,
    validate_inventory,
)


def inventory(*, entry_path="src/**", kind="canonical"):
    entry = {
        "name": "canonical-source",
        "kind": kind,
        "path_glob": entry_path,
        "canonical": "simplicio_agent" if kind != "canonical" else None,
        "owner": "test",
        "reason": "fixture",
    }
    if kind in {"shim", "bridge"}:
        entry["expiry"] = "2026-12-31"
    return {
        "schema": INVENTORY_SCHEMA,
        "version": 1,
        "canonical_names": {"namespace": "simplicio_agent"},
        "legacy_names": ["hermes-agent", "HERMES_", "HermesCLI"],
        "entries": [entry],
    }


def test_inventory_requires_expiry_for_temporary_surfaces():
    value = inventory(kind="shim")
    value["entries"][0].pop("expiry")
    assert "entries[0].expiry is required for shim" in validate_inventory(value)


def test_inventory_rejects_non_object_entry():
    value = inventory()
    value["entries"].append("not-an-entry")
    assert "entries[1] must be an object" in validate_inventory(value)


def test_source_search_classifies_legacy_outside_bridge_as_blocking(tmp_path: Path):
    path = tmp_path / "src" / "main.py"
    path.parent.mkdir()
    path.write_text(
        "import hermes_agent\nfrom simplicio_agent import Agent\n", encoding="utf-8"
    )
    findings = scan_source(tmp_path, inventory(), paths=["src/main.py"])
    assert [finding.kind for finding in findings] == ["legacy", "canonical"]
    assert findings[0].classification == "unclassified_legacy"


def test_bridge_inventory_is_nonblocking_but_scope_stays_unverified(tmp_path: Path):
    value = inventory(entry_path="compat.py", kind="shim")
    path = tmp_path / "compat.py"
    path.write_text("name = 'hermes-agent'\n", encoding="utf-8")
    source = scan_source(tmp_path, value, paths=["compat.py"])
    receipt = build_receipt(value, source=source, build=[], runtime=[])
    assert receipt["sections"]["source"]["blocking_count"] == 0
    assert receipt["migration_scope"] == "UNVERIFIED"
    assert receipt["remaining_migration_entries"] == ["canonical-source"]


def test_build_scan_handles_zip_and_runtime_snapshot(tmp_path: Path):
    wheel = tmp_path / "fixture.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pkg/app.py", "name = 'simplicio_agent'\n")
    findings = scan_build([wheel], inventory())
    assert findings[0].surface == "build"
    assert findings[0].classification == "canonical"

    runtime = scan_runtime(
        {"module": "hermes-agent", "namespace": "simplicio_agent"}, inventory()
    )
    assert {finding.kind for finding in runtime} == {"legacy", "canonical"}


def test_build_scan_handles_tar_and_receipt_digest_is_stable(tmp_path: Path):
    archive_path = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"module = 'simplicio_agent'\n"
        info = tarfile.TarInfo("pkg/app.py")
        info.size = len(payload)
        archive.addfile(info, BytesIO(payload))
    first = build_receipt(
        inventory(),
        source=[],
        build=scan_build([archive_path], inventory()),
        runtime=[],
    )
    second = build_receipt(
        inventory(),
        source=[],
        build=scan_build([archive_path], inventory()),
        runtime=[],
    )
    assert first["digest"] == second["digest"]


def test_audit_marks_omitted_artifact_and_runtime_surfaces_unverified(tmp_path: Path):
    result = audit(tmp_path, inventory(), paths=[])
    assert result["migration_scope"] == "UNVERIFIED"
    assert result["unverified_surfaces"] == ["build", "runtime"]
