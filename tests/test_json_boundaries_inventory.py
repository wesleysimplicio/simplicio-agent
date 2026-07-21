"""Contract tests for the reviewed JSON boundary inventory (issue #517)."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path


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
