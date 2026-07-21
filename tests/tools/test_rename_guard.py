"""Fixture corpus for the branding-regression guard (issue #194, #187)."""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from tools.rename_guard.scanner import scan, to_report, tracked_files
from tools.rename_guard.inventory import build_manifest, validate_allowlist, validate_manifest


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


@pytest.mark.live_system_guard_bypass
def test_unicode_git_paths_are_decoded_without_host_codec_failure(tmp_path):
    """Git paths are UTF-8 even when Windows Python uses cp1252 by default."""
    repo = _init_repo(tmp_path, {"src/café.py": "hermes = True\n"})

    assert "src/café.py" in tracked_files(repo)
    report = to_report(scan(repo, {"exclude_globs": []}, [], {}, date(2026, 1, 1)))

    assert report["schema"] == "simplicio.rename-guard/v1"
    assert report["new_count"] == 1
    assert report["occurrences"][0]["path"] == "src/café.py"


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


def test_summary_counts_by_class_and_surface(tmp_path):
    """issue #187 AC: 'Summary conta por surface/classification sem inventar
    completion' — the top-level report carries aggregate counts derived
    straight from the occurrence list, not a fabricated completion figure."""
    repo = _init_repo(tmp_path, {
        "src/app.py": "hermes_token = 1\n",
        "tests/fixture.py": "hermes_fixture = 1\n",
    })
    allowlist = [{
        "path_glob": "tests/*", "term": None, "class": "historical-fixture",
        "reason": "test fixture", "owner": "x", "expiry": None,
    }]
    occurrences = scan(repo, {"exclude_globs": []}, allowlist, {}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["by_class"] == {"historical-fixture": 1, "new": 1}
    assert report["by_surface"] == {"src": 1, "tests": 1}
    assert sum(report["by_class"].values()) == report["total"]
    assert sum(report["by_surface"].values()) == report["total"]


def test_allowlisted_private_internal_symbol_passes(tmp_path):
    """False positive corpus (#187 evidence requirement): a private,
    internal-only symbol reviewed and classified, not a public regression."""
    repo = _init_repo(tmp_path, {"internal/_priv.py": "_hermes_internal_flag = True\n"})
    allowlist = [{
        "path_glob": "internal/*", "term": None, "class": "private-internal-reviewed",
        "reason": "private module-internal flag, reviewed, not public API", "owner": "x",
        "expiry": None,
    }]
    occurrences = scan(repo, {"exclude_globs": []}, allowlist, {}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["new_count"] == 0
    assert report["occurrences"][0]["class"] == "private-internal-reviewed"


def test_allowlisted_alias_passes(tmp_path):
    """False positive corpus (#187 evidence requirement): a deprecated CLI
    alias kept for compatibility, explicitly classified as such."""
    repo = _init_repo(tmp_path, {"cli.py": "ALIASES = ['hermes-agent']\n"})
    allowlist = [{
        "path_glob": "cli.py", "term": None, "class": "compatibility-temporary",
        "reason": "deprecated alias kept working for backward compatibility", "owner": "x",
        "expiry": None,
    }]
    occurrences = scan(repo, {"exclude_globs": []}, allowlist, {}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["new_count"] == 0
    assert report["occurrences"][0]["class"] == "compatibility-temporary"


def test_repo_capability_contract_and_rename_status_docs_are_allowlisted():
    """The two docs added after the baseline freeze (capability contract
    skill catalog + this issue's own status report) quote legacy internal
    paths verbatim; they must be explicitly allowlisted, not silently
    swallowed by an ever-growing baseline (#187 AC: 'Allowlist usa
    path+pattern+reason+expiry/owner; não regex global permissiva')."""
    import json as _json

    from tools.rename_guard.scanner import DEFAULT_ALLOWLIST

    entries = _json.loads(DEFAULT_ALLOWLIST.read_text(encoding="utf-8"))["entries"]
    globs = {entry["path_glob"] for entry in entries}
    assert "docs/SIMPLICIO_AGENT_CAPABILITY_CONTRACT.md" in globs
    assert "docs/rename-inventory-status.md" in globs
    for entry in entries:
        if entry["path_glob"] in {
            "docs/SIMPLICIO_AGENT_CAPABILITY_CONTRACT.md",
            "docs/rename-inventory-status.md",
        }:
            assert entry["owner"]
            assert entry["reason"]


def test_current_packaging_debt_is_classified_and_owned():
    """Public packaging debt must remain visible as a migration class.

    The inventory may allow a legacy occurrence temporarily, but it must keep
    the owning issue in machine-readable data instead of hiding the occurrence
    in the numeric baseline.
    """
    import json as _json
    from tools.rename_guard.scanner import DEFAULT_ALLOWLIST

    entries = _json.loads(
        DEFAULT_ALLOWLIST.read_text(encoding="utf-8")
    )["entries"]
    by_path = {entry["path_glob"]: entry for entry in entries}
    for path in ("package.json", "packaging/homebrew/hermes-agent.rb", "packaging/homebrew/README.md"):
        entry = by_path[path]
        assert entry["class"] == "public-must-migrate"
        assert entry["issue"] == "#118"
        assert entry["owner"]
        assert entry["reason"]

    assert by_path["DOD.md"]["class"] == "KEEP_INTERNAL"


def test_repo_baseline_and_allowlist_are_valid_and_guard_passes_on_head():
    """The live repo's own baseline.json/allowlist.json must be internally
    consistent and the guard must currently report zero new occurrences —
    this is the CI gate itself (issue #194 AC: 'roda pelo wrapper de testes e
    CI'; issue #187 AC: 'Public occurrences não podem ficar UNCLASSIFIED')."""
    from tools.rename_guard.scanner import DEFAULT_ALLOWLIST, DEFAULT_BASELINE, DEFAULT_CONFIG, main

    assert DEFAULT_ALLOWLIST.exists()
    assert DEFAULT_BASELINE.exists()
    assert DEFAULT_CONFIG.exists()
    exit_code = main(["--root", str(Path(__file__).resolve().parents[2])])
    assert exit_code == 0


def test_allowlist_contract_requires_path_scoped_owned_exceptions():
    import json as _json

    from tools.rename_guard.scanner import DEFAULT_ALLOWLIST

    entries = _json.loads(DEFAULT_ALLOWLIST.read_text(encoding="utf-8"))["entries"]
    assert validate_allowlist(entries, date(2026, 7, 21)) == []
    assert all(entry["path_glob"] not in {"*", "**"} for entry in entries)


def test_inventory_preserves_compatibility_context_and_provenance(tmp_path):
    repo = _init_repo(tmp_path, {"cli.py": "ALIASES = ['hermes-agent']\n"})
    allowlist = [{
        "path_glob": "cli.py", "term": None, "class": "compatibility-temporary",
        "reason": "deprecated alias remains callable during migration", "owner": "x",
        "issue": "#118", "expiry": "2026-12-31",
    }]
    occurrences = scan(repo, {"exclude_globs": []}, allowlist, {}, date(2026, 7, 21))
    manifest = build_manifest(occurrences, allowlist, {})
    record = manifest["records"][0]
    assert record["path"] == "cli.py"
    assert record["line"] == 1
    assert record["token"] == "hermes"
    assert record["context_class"] == "compatibility-temporary"
    assert record["classification"] == "compatibility-temporary"
    assert record["artifact"] == "source-tree"
    assert record["origin"] == "source"
    assert validate_manifest(manifest) == []


def test_inventory_fails_closed_for_unclassified_baseline(tmp_path):
    repo = _init_repo(tmp_path, {"legacy/old.py": "hermes_legacy = True\n"})
    occurrences = scan(repo, {"exclude_globs": []}, [], {"legacy/old.py": 1}, date(2026, 7, 21))
    manifest = build_manifest(occurrences, [], {})
    errors = validate_manifest(manifest)
    assert any("unclassified/error occurrence" in error for error in errors)
