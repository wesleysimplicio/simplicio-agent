"""Contract tests for the reviewed JSON boundary inventory (issue #517)."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from scripts.check_json_boundaries import findings, load_inventory, main


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "config" / "json-boundaries.toml"
REQUIRED_BOUNDARY_FIELDS = {
    "category_id",
    "paths",
    "producer",
    "consumer",
    "lifecycle",
    "category",
    "owner",
    "target_format",
    "rationale",
}
JSON_SUFFIXES = (".json", ".jsonl", ".ndjson")
JSON_CONTENT_PATHS = {"runtime.lock"}


def _tracked_json_paths() -> set[str]:
    output = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        close_fds=False,
    )
    return {
        path
        for path in output.splitlines()
        if path.lower().endswith(JSON_SUFFIXES) or path in JSON_CONTENT_PATHS
    }


def test_inventory_covers_every_tracked_json_file() -> None:
    data = tomllib.loads(INVENTORY.read_text(encoding="utf-8"))
    boundaries = data["boundary"]
    inventory_paths = [path for boundary in boundaries for path in boundary["paths"]]

    assert data["format"] == "simplicio-agent.json-boundaries/v1"
    assert data["issue"] == 517
    assert set(data["source_extensions"]) == set(JSON_SUFFIXES)
    assert len(inventory_paths) == len(set(inventory_paths))
    assert set(inventory_paths) == _tracked_json_paths()


def test_each_boundary_has_review_fields_and_valid_paths() -> None:
    data = tomllib.loads(INVENTORY.read_text(encoding="utf-8"))
    tracked_paths = _tracked_json_paths()

    for boundary in data["boundary"]:
        assert REQUIRED_BOUNDARY_FIELDS <= boundary.keys()
        assert boundary["paths"]
        assert set(boundary["paths"]) <= tracked_paths
        for field in REQUIRED_BOUNDARY_FIELDS - {"paths"}:
            assert isinstance(boundary[field], str)
            assert boundary[field].strip()


def test_audited_modules_are_present_and_target_runtime_owned_state() -> None:
    data = tomllib.loads(INVENTORY.read_text(encoding="utf-8"))
    audit = next(item for item in data["audit"] if item["kind"] == "module")

    assert audit["paths"]
    assert all((ROOT / path).is_file() for path in audit["paths"])
    assert "HBP" in audit["target_format"]
    assert "HBI" in audit["target_format"]
    assert "TOML" in audit["target_format"]


def test_comment_only_json_mentions_are_not_findings(tmp_path: Path) -> None:
    source = tmp_path / "adapter.py"
    source.write_text("# json.loads(payload)\n# sessions.json is legacy\n", encoding="utf-8")

    assert findings(tmp_path) == []


def test_external_adapter_is_an_exact_strict_mode_exception(
    tmp_path: Path, monkeypatch
) -> None:
    adapter = tmp_path / "adapter.py"
    adapter.write_text("import json\njson.loads(payload)\n", encoding="utf-8")
    inventory = tmp_path / "inventory.toml"
    inventory.write_text(
        """format = 'test'\n\n[[audit]]\nkind = 'adapter'\npaths = ['adapter.py']\nproducer = 'external protocol'\nconsumer = 'adapter'\nlifecycle = 'wire format'\ncategory = 'external protocol adapter'\nowner = 'test owner'\ntarget_format = 'preserve external JSON'\nstatus = 'exception'\nreason = 'protocol-owned wire format'\nexpires = '2099-12-31'\n""",
        encoding="utf-8",
    )

    assert load_inventory(inventory)["adapter.py"]["status"] == "exception"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_json_boundaries.py",
            "--root",
            str(tmp_path),
            "--inventory",
            str(inventory),
            "--mode",
            "strict",
        ],
    )
    assert main() == 0
