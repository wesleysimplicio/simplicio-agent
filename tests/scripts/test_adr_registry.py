from __future__ import annotations

from pathlib import Path

from scripts.adr_registry import iter_adrs, validate
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


def test_registry_reports_duplicate_numbers_and_stale_index(tmp_path):
    _write(tmp_path, "ADR-0001-first.md")
    _write(tmp_path, "ADR-0001-second.md")
    index = tmp_path / "INDEX.md"
    index.write_text("# Architecture Decision Records\n", encoding="utf-8")
    errors = validate(iter_adrs(tmp_path), require_index=index)
    assert any("duplicate files" in error for error in errors)
    assert any("index missing" in error for error in errors)
