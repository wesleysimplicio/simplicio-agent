from __future__ import annotations

import sys
from pathlib import Path

from scripts.adr_registry import iter_adrs, validate
from scripts import check_adr_registry, gen_adr_index
from scripts.gen_adr_index import render


def _write(root: Path, name: str, title: str = "Decision") -> None:
    (root / name).write_text(
        f"# {title}\n\nStatus: accepted\nDate: 2026-07-14\n",
        encoding="utf-8",
    )


def test_registry_and_generated_index_are_deterministic(tmp_path):
    _write(tmp_path, "ADR-0001-first.md", "First")
    _write(tmp_path, "ADR-0002-second.md", "Second")
    entries = iter_adrs(tmp_path)
    index = tmp_path / "INDEX.md"
    index.write_text(render(entries), encoding="utf-8")
    assert validate(entries, require_index=index) == []
    assert render(entries) == render(iter_adrs(tmp_path))


def test_generator_main_is_idempotent(tmp_path, monkeypatch):
    root = tmp_path / "docs" / "architecture"
    root.mkdir(parents=True)
    _write(root, "ADR-0002-second.md", "Second")
    _write(root, "ADR-0001-first.md", "First")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["gen_adr_index.py"])

    assert gen_adr_index.main() == 0
    first = (root / "INDEX.md").read_text(encoding="utf-8")
    assert gen_adr_index.main() == 0
    assert (root / "INDEX.md").read_text(encoding="utf-8") == first


def test_registry_reports_duplicate_numbers_and_stale_index(tmp_path):
    _write(tmp_path, "ADR-0001-first.md")
    _write(tmp_path, "ADR-0001-second.md")
    index = tmp_path / "INDEX.md"
    index.write_text("# Architecture Decision Records\n", encoding="utf-8")
    errors = validate(iter_adrs(tmp_path), require_index=index)
    assert any("duplicate files" in error for error in errors)
    assert any("index missing" in error for error in errors)


def test_registry_reads_markdown_field_prefixes(tmp_path):
    (tmp_path / "ADR-0001-first.md").write_text(
        "# First\n\n**Status:** accepted\n- Date: 2026-07-14\n",
        encoding="utf-8",
    )

    entry = iter_adrs(tmp_path)[0]
    assert entry["status"] == "accepted"
    assert entry["date"] == "2026-07-14"


def test_checker_rejects_stale_generated_index(tmp_path, monkeypatch):
    root = tmp_path / "docs" / "architecture"
    root.mkdir(parents=True)
    _write(root, "ADR-0001-first.md", "First")
    index = root / "INDEX.md"
    index.write_text(render(iter_adrs(root)), encoding="utf-8")
    index.write_text(
        index.read_text(encoding="utf-8").replace("First", "Changed"), encoding="utf-8"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_adr_registry.py", "--root", str(root), "--index", str(index)],
    )

    assert check_adr_registry.main() == 1
