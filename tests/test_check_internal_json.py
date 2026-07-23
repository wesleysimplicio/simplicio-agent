from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from scripts.check_internal_json import InventoryError, load_inventory, render_markdown, scan


def _inventory(path: Path, body: str = "") -> Path:
    path.write_text(
        """format = \"simplicio-agent.json-boundaries/v1\"
reviewed_at = \"2026-07-23\"
expires_at = \"2026-10-21\"
source_extensions = [\".json\"]
scan_roots = [\"state\"]
max_files = 10
max_bytes = 1024
"""
        + body,
        encoding="utf-8",
    )
    return path


def test_scan_is_bounded_and_renders_markdown(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "allowed.json").write_text("{}", encoding="utf-8")
    inventory = _inventory(
        tmp_path / "inventory.toml",
        """[[boundary]]
category_id = \"tooling\"
paths = [\"state/allowed.json\"]
owner = \"agent-quality\"
rationale = \"Tooling input remains JSON at this boundary.\"
""",
    )

    result = scan(tmp_path, inventory)

    assert result.passed
    report = render_markdown(result, Path("inventory.toml"))
    assert "Status: **PASS**" in report
    assert "Exact exceptions: **1**" in report
    assert "Every bounded candidate has an exact registry entry." in report


def test_scan_reports_unclassified_json(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "unclassified.json").write_text("{}", encoding="utf-8")
    inventory = _inventory(tmp_path / "inventory.toml")

    result = scan(tmp_path, inventory)

    assert result.findings == ("state/unclassified.json",)
    assert "state/unclassified.json" in render_markdown(result, Path("inventory.toml"))


def test_inventory_rejects_globs_missing_metadata_and_expiry(tmp_path: Path) -> None:
    glob_inventory = _inventory(
        tmp_path / "glob.toml",
        """[[boundary]]
category_id = \"tooling\"
paths = [\"state/*.json\"]
owner = \"agent-quality\"
rationale = \"not exact\"
""",
    )
    with pytest.raises(InventoryError, match="exact POSIX path"):
        load_inventory(glob_inventory)

    missing_owner = _inventory(
        tmp_path / "owner.toml",
        """[[boundary]]
category_id = \"tooling\"
paths = [\"state/allowed.json\"]
rationale = \"missing owner\"
""",
    )
    with pytest.raises(InventoryError, match="missing owner"):
        load_inventory(missing_owner)

    expired = _inventory(tmp_path / "expired.toml").read_text(encoding="utf-8").replace(
        'expires_at = "2026-10-21"', 'expires_at = "2026-07-22"'
    )
    expired_path = tmp_path / "expired.toml"
    expired_path.write_text(expired, encoding="utf-8")
    with pytest.raises(InventoryError, match="expired"):
        load_inventory(expired_path, today=dt.date(2026, 7, 23))
