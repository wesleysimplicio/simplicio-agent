from __future__ import annotations

import zipfile
from pathlib import Path

from scripts.check_json_boundaries import QUALITY_SCHEMA, quality_report


def _inventory(path: Path, *, exception: str | None = None) -> Path:
    entry = ""
    if exception:
        entry = f'''
[[audit]]
kind = "adapter"
paths = ["{exception}"]
producer = "external protocol"
consumer = "adapter"
lifecycle = "wire format"
category = "external protocol adapter"
owner = "agent-quality"
target_format = "preserve external JSON"
status = "exception"
reason = "external protocol owns this JSON wire format"
expires = "2099-12-31"
'''
    path.write_text(
        '''format = "simplicio-agent.json-boundaries/v1"
reviewed_at = "2026-07-23"
expires_at = "2099-12-31"
source_extensions = [".py"]
scan_roots = ["source"]
max_files = 20
max_bytes = 4096
'''
        + entry,
        encoding="utf-8",
    )
    return path


def test_quality_gate_passes_clean_source(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "clean.py").write_text("value = 1\n", encoding="utf-8")

    report = quality_report(tmp_path, _inventory(tmp_path / "inventory.toml"))

    assert report["schema"] == QUALITY_SCHEMA
    assert report["status"] == "pass"
    assert report["ok"] is True


def test_quality_gate_blocks_unclassified_finding(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "finding.py").write_text(
        "import json\njson.loads(payload)\n", encoding="utf-8"
    )

    report = quality_report(tmp_path, _inventory(tmp_path / "inventory.toml"))

    assert report["status"] == "block"
    assert report["source"]["unknown"][0]["path"] == "source/finding.py"


def test_quality_gate_preserves_external_json_exception(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "external.py").write_text(
        "import json\njson.loads(payload)\n", encoding="utf-8"
    )

    report = quality_report(
        tmp_path,
        _inventory(tmp_path / "inventory.toml", exception="source/external.py"),
    )

    assert report["ok"] is True
    assert report["source"]["exceptions"][0]["reason"].startswith("external protocol")


def test_quality_gate_scans_package_members_and_blocks_findings(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    package = tmp_path / "dist" / "agent.whl"
    package.parent.mkdir()
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("agent/runtime.py", "import json\njson.loads(payload)\n")

    report = quality_report(
        tmp_path,
        _inventory(tmp_path / "inventory.toml"),
        packages=(package,),
        require_package=True,
    )

    assert report["status"] == "block"
    assert report["packages"][0]["unknown"][0]["path"] == "agent/runtime.py"


def test_quality_gate_reports_unavailable_package_evidence(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()

    report = quality_report(
        tmp_path,
        _inventory(tmp_path / "inventory.toml"),
        require_package=True,
    )

    assert report["ok"] is False
    assert report["evidence"]["package"] == {
        "value": None,
        "reason": "package artifact was not provided",
    }
