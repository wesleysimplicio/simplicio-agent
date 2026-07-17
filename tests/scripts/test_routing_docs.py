from __future__ import annotations

from pathlib import Path

from scripts.check_routing_docs import find_violations, main


def test_no_conflicting_routing_phrases_on_real_repo():
    repo_root = Path(__file__).resolve().parents[2]
    assert find_violations(repo_root) == []


def test_detects_conflicting_phrase(tmp_path):
    (tmp_path / "some-skill.md").write_text(
        "Use Hermes-native tools first for reading and searching.\n",
        encoding="utf-8",
    )
    violations = find_violations(tmp_path)
    assert len(violations) == 1
    assert "some-skill.md:1" in violations[0]


def test_ignores_archive_and_changelog(tmp_path):
    archive_dir = tmp_path / "archive" / "website"
    archive_dir.mkdir(parents=True)
    (archive_dir / "old.md").write_text(
        "Prefer Hermes native tools first.\n", encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "Hermes-native tools first was the old rule.\n", encoding="utf-8"
    )
    assert find_violations(tmp_path) == []


def test_main_returns_nonzero_on_violation(tmp_path, capsys):
    (tmp_path / "doc.md").write_text(
        "Hermes-native orientation first.\n", encoding="utf-8"
    )
    assert main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "conflicting phrase" in captured.err
