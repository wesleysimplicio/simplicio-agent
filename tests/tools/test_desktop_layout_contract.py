"""Focused tests for the desktop layout contract replacement for issue #126."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.desktop_layout_contract import (
    DESKTOP_LAYOUT_SCHEMA,
    DesktopLayoutAmbiguousError,
    DesktopLayoutMissingError,
    build_desktop_layout_receipt,
    locate_desktop_root,
)


def _desktop_fixture(root: Path) -> None:
    (root / "desktop").mkdir()
    (root / "package.json").write_text('{"name": "fixture"}\n', encoding="utf-8")


def test_locates_canonical_desktop_root_and_returns_json_ready_receipt(
    tmp_path: Path,
) -> None:
    _desktop_fixture(tmp_path)
    receipt = build_desktop_layout_receipt(tmp_path, manifest_paths=["package.json"])
    assert locate_desktop_root(tmp_path) == tmp_path / "desktop"
    assert receipt.ok is True
    assert receipt.canonical_root == "desktop"
    assert receipt.schema == DESKTOP_LAYOUT_SCHEMA
    payload = receipt.to_dict()
    assert json.loads(receipt.to_json()) == payload
    assert payload["proof"]["npm_build"]["status"] == "unverified"
    assert payload["proof"]["installer"]["status"] == "unverified"
    assert "npm build and installer proof remain unverified" in payload["notes"]


def test_falls_back_to_legacy_desktop_root(tmp_path: Path) -> None:
    (tmp_path / "apps" / "desktop").mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{"name": "legacy", "path": "apps/desktop"}\n', encoding="utf-8"
    )
    receipt = build_desktop_layout_receipt(tmp_path, manifest_paths=["package.json"])
    assert locate_desktop_root(tmp_path) == tmp_path / "apps" / "desktop"
    assert receipt.ok is True
    assert receipt.canonical_root == "apps/desktop"
    assert receipt.stale_references == ()


def test_rejects_ambiguous_layout(tmp_path: Path) -> None:
    (tmp_path / "desktop").mkdir()
    (tmp_path / "apps" / "desktop").mkdir(parents=True)
    with pytest.raises(
        DesktopLayoutAmbiguousError, match="both desktop and apps/desktop"
    ):
        locate_desktop_root(tmp_path)


def test_rejects_missing_layout(tmp_path: Path) -> None:
    with pytest.raises(
        DesktopLayoutMissingError, match="expected desktop or apps/desktop"
    ):
        locate_desktop_root(tmp_path)


@pytest.mark.parametrize(
    "reference", ["apps/desktop/package.json", r"apps\desktop\package.json"]
)
def test_reports_stale_reference_in_selected_manifest(
    tmp_path: Path, reference: str
) -> None:
    _desktop_fixture(tmp_path)
    consumer = tmp_path / "selected.json"
    consumer.write_text(json.dumps({"desktop": reference}) + "\n", encoding="utf-8")
    receipt = build_desktop_layout_receipt(tmp_path, manifest_paths=["selected.json"])
    assert receipt.ok is False
    assert len(receipt.stale_references) == 1
    assert receipt.stale_references[0].path == "selected.json"
    assert receipt.stale_references[0].line == 1


def test_selected_manifests_are_bounded_and_missing_files_fail_closed(
    tmp_path: Path,
) -> None:
    _desktop_fixture(tmp_path)
    receipt = build_desktop_layout_receipt(
        tmp_path, manifest_paths=["package.json", "not-selected.json"]
    )
    assert receipt.ok is False
    assert receipt.scanned_manifests == ("package.json",)
    assert receipt.missing_manifests == ("not-selected.json",)
    assert receipt.stale_references == ()


def test_selected_manifest_cannot_escape_repo_root(tmp_path: Path) -> None:
    _desktop_fixture(tmp_path)
    with pytest.raises(ValueError, match="stay inside repository"):
        build_desktop_layout_receipt(tmp_path, manifest_paths=["../outside.json"])
