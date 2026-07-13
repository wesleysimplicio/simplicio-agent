"""Fixture corpus for the branding-regression guard (issue #194)."""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from tools.rename_guard.scanner import scan, to_report


def _init_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path, check=True,
    )
    return tmp_path


def test_new_unclassified_occurrence_fails(tmp_path):
    repo = _init_repo(tmp_path, {"src/app.py": "# Powered by Hermes Agent\n"})
    occurrences = scan(repo, {"exclude_globs": []}, [], {}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["new_count"] == 1
    assert report["occurrences"][0]["class"] == "new"


def test_allowlisted_license_header_passes(tmp_path):
    repo = _init_repo(tmp_path, {"LICENSE": "Copyright (c) Hermes Project Authors\n"})
    allowlist = [{
        "path_glob": "LICENSE", "term": None, "class": "credit",
        "reason": "license attribution", "owner": "x", "expiry": None,
    }]
    occurrences = scan(repo, {"exclude_globs": []}, allowlist, {}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["new_count"] == 0
    assert report["occurrences"][0]["class"] == "credit"


def test_allowlisted_upstream_link_passes(tmp_path):
    repo = _init_repo(tmp_path, {"docs/notes.md": "See https://github.com/upstream/hermes\n"})
    allowlist = [{
        "path_glob": "docs/*", "term": None, "class": "upstream",
        "reason": "link to upstream project", "owner": "x", "expiry": None,
    }]
    occurrences = scan(repo, {"exclude_globs": []}, allowlist, {}, date(2026, 1, 1))
    assert to_report(occurrences)["new_count"] == 0


def test_expired_allowlist_entry_falls_back_to_new(tmp_path):
    repo = _init_repo(tmp_path, {"src/app.py": "hermes_token = 1\n"})
    allowlist = [{
        "path_glob": "src/*", "term": None, "class": "alias",
        "reason": "temporary alias", "owner": "x", "expiry": "2020-01-01",
    }]
    occurrences = scan(repo, {"exclude_globs": []}, allowlist, {}, date(2026, 1, 1))
    assert to_report(occurrences)["new_count"] == 1


def test_baseline_grandfathers_existing_occurrence(tmp_path):
    repo = _init_repo(tmp_path, {"legacy/old.py": "hermes_legacy = True\n"})
    occurrences = scan(repo, {"exclude_globs": []}, [], {"legacy/old.py": 1}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["new_count"] == 0
    assert report["occurrences"][0]["class"] == "baseline"


def test_regression_beyond_baseline_count_fails(tmp_path):
    repo = _init_repo(tmp_path, {
        "legacy/old.py": "hermes_one = 1\nhermes_two = 2\n",
    })
    # baseline only grandfathers 1 occurrence in this file; the 2nd is a regression
    occurrences = scan(repo, {"exclude_globs": []}, [], {"legacy/old.py": 1}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["new_count"] == 1
    classes = sorted(o["class"] for o in report["occurrences"])
    assert classes == ["baseline", "new"]


@pytest.mark.parametrize("token", ["Hermes", "HERMES", "hermes", "her-mes", "her_mes", "her mes"])
def test_case_spacing_hyphen_variants_detected(tmp_path, token):
    repo = _init_repo(tmp_path, {"src/app.py": f"NAME = '{token}'\n"})
    occurrences = scan(repo, {"exclude_globs": []}, [], {}, date(2026, 1, 1))
    assert to_report(occurrences)["new_count"] == 1


def test_binary_and_excluded_paths_are_skipped(tmp_path):
    repo = _init_repo(tmp_path, {
        "vendor/dist/bundle.min.js": "hermes",
        "node_modules/pkg/index.js": "hermes",
    })
    occurrences = scan(
        repo, {"exclude_globs": ["node_modules/*"]}, [], {}, date(2026, 1, 1)
    )
    paths = {o.path for o in occurrences}
    assert "node_modules/pkg/index.js" not in paths
    assert "vendor/dist/bundle.min.js" in paths  # not excluded, still a real .js text file


def test_output_is_machine_readable_with_required_fields(tmp_path):
    repo = _init_repo(tmp_path, {"src/app.py": "hermes\n"})
    occurrences = scan(repo, {"exclude_globs": []}, [], {}, date(2026, 1, 1))
    report = to_report(occurrences)
    occ = report["occurrences"][0]
    assert set(occ) == {"path", "line", "surface", "term", "class", "reason"}


def test_repo_baseline_and_allowlist_are_valid_and_guard_passes_on_head():
    """The live repo's own baseline.json/allowlist.json must be internally
    consistent and the guard must currently report zero new occurrences —
    this is the CI gate itself (issue #194 AC: 'roda pelo wrapper de testes e CI')."""
    from tools.rename_guard.scanner import DEFAULT_ALLOWLIST, DEFAULT_BASELINE, DEFAULT_CONFIG, main

    assert DEFAULT_ALLOWLIST.exists()
    assert DEFAULT_BASELINE.exists()
    assert DEFAULT_CONFIG.exists()
    exit_code = main(["--root", str(Path(__file__).resolve().parents[2])])
    assert exit_code == 0
