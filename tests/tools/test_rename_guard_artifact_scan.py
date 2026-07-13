"""Fixture corpus for the packaged-artifact branding-regression guard.

Covers issue #194's "packaged artifacts" AC: a wheel or sdist that leaks a
new, unclassified old-brand occurrence must fail the same way the
source-scan guard does, using synthetic in-memory archives (no real build
toolchain, no network) so this suite stays as fast/deterministic as
``test_rename_guard.py``.
"""
from __future__ import annotations

import tarfile
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest

from tools.rename_guard.artifact_scan import (
    iter_archive_members,
    scan_archive,
    scan_members,
)
from tools.rename_guard.scanner import to_report


def _make_wheel(tmp_path: Path, files: dict[str, str]) -> Path:
    wheel_path = tmp_path / "pkg-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
    return wheel_path


def _make_sdist(tmp_path: Path, files: dict[str, str]) -> Path:
    sdist_path = tmp_path / "pkg-0.1.0.tar.gz"
    with tarfile.open(sdist_path, "w:gz") as tf:
        for rel, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=rel)
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
    return sdist_path


def test_wheel_with_new_unclassified_occurrence_fails(tmp_path):
    wheel = _make_wheel(tmp_path, {"pkg/app.py": "# Powered by Hermes Agent\n"})
    occurrences = scan_archive(wheel, {"exclude_globs": []}, [], {}, date(2026, 1, 1), "wheel:")
    report = to_report(occurrences)
    assert report["new_count"] == 1
    assert report["occurrences"][0]["path"] == "wheel:pkg/app.py"
    assert report["occurrences"][0]["class"] == "new"


def test_sdist_with_new_unclassified_occurrence_fails(tmp_path):
    sdist = _make_sdist(tmp_path, {"pkg-0.1.0/pkg/app.py": "hermes_legacy = True\n"})
    occurrences = scan_archive(sdist, {"exclude_globs": []}, [], {}, date(2026, 1, 1), "sdist:")
    assert to_report(occurrences)["new_count"] == 1


def test_allowlisted_dist_info_metadata_passes(tmp_path):
    wheel = _make_wheel(tmp_path, {
        "pkg-0.1.0.dist-info/METADATA": "Name: hermes-agent\nVersion: 0.1.0\n",
    })
    allowlist = [{
        "path_glob": "*.dist-info/METADATA", "term": None, "class": "credit",
        "reason": "generated from pyproject.toml", "owner": "x", "expiry": None,
    }]
    occurrences = scan_archive(wheel, {"exclude_globs": []}, allowlist, {}, date(2026, 1, 1))
    report = to_report(occurrences)
    assert report["new_count"] == 0
    assert report["occurrences"][0]["class"] == "credit"


def test_baseline_shared_with_source_scan_by_relative_path(tmp_path):
    # A path that ships unchanged from source into the wheel (e.g. a
    # module under an existing KEEP_INTERNAL allowlist path) should be
    # classifiable via the exact same baseline counts keyed by that path.
    wheel = _make_wheel(tmp_path, {"hermes_cli/main.py": "# hermes\n"})
    occurrences = scan_archive(
        wheel, {"exclude_globs": []}, [], {"hermes_cli/main.py": 1}, date(2026, 1, 1),
    )
    report = to_report(occurrences)
    assert report["new_count"] == 0
    assert report["occurrences"][0]["class"] == "baseline"


def test_binary_and_excluded_members_are_skipped(tmp_path):
    wheel = _make_wheel(tmp_path, {
        "pkg/assets/logo.png": "hermes",
        "pkg/vendor/bundle.min.js": "hermes",
    })
    occurrences = scan_archive(
        wheel, {"exclude_globs": ["pkg/vendor/*"]}, [], {}, date(2026, 1, 1),
    )
    paths = {o.path for o in occurrences}
    assert not any("logo.png" in p for p in paths)  # binary extension, always skipped
    assert not any("bundle.min.js" in p for p in paths)  # excluded glob


def test_unrecognized_archive_type_raises():
    with pytest.raises(ValueError):
        iter_archive_members(Path("not-an-archive.txt"))


def test_output_is_machine_readable_with_required_fields(tmp_path):
    wheel = _make_wheel(tmp_path, {"pkg/app.py": "hermes\n"})
    occurrences = scan_archive(wheel, {"exclude_globs": []}, [], {}, date(2026, 1, 1), "wheel:")
    occ = to_report(occurrences)["occurrences"][0]
    assert set(occ) == {"path", "line", "surface", "term", "class", "reason"}


def test_scan_members_matches_scan_archive_for_zip(tmp_path):
    wheel = _make_wheel(tmp_path, {"pkg/app.py": "hermes\n"})
    from_archive = to_report(scan_archive(wheel, {"exclude_globs": []}, [], {}, date(2026, 1, 1)))
    from_members = to_report(
        scan_members(iter_archive_members(wheel), {"exclude_globs": []}, [], {}, date(2026, 1, 1))
    )
    assert from_archive == from_members
