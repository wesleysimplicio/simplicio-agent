#!/usr/bin/env python3
"""Packaged-artifact branding-regression guard (issue #194).

``scanner.py`` only ever inspects git-tracked source files. That misses the
one place a leak actually reaches a user: the built Python distributions
(wheel + sdist) that ``upload_to_pypi.yml`` builds and publishes. A
generator, a bundled asset, or build-tool metadata can reintroduce the old
brand into a public artifact even when every git-tracked source file is
clean — this module closes that gap for the wheel/sdist slice of the
packaging pipeline.

Two layers, matching the "PR smoke vs. release deep scan" split from the
issue's acceptance criteria:

- ``scan_archive`` / ``scan_members`` — pure, fast, and unit-testable: given
  an already-built wheel (``.whl``, a zip) or sdist (``.tar.gz``), extract
  every text member in-memory and re-run ``scanner``'s exact TERM_PATTERN +
  allowlist + baseline classification over it. No git repo, no build
  toolchain, no network — this is what the test suite exercises directly
  with synthetic fixtures.
- ``main`` — the CLI entry point that actually builds the project's wheel +
  sdist with ``uv build`` (matching the real command
  ``upload_to_pypi.yml`` already runs) into a throwaway temp directory, then
  calls the pure scan functions above. This is the "deep scan" path: slower
  (a real build), so it is wired into the release-only leg of CI rather
  than every PR.

Out of scope here (tracked by the issue's broader plan, not this checker):
Electron desktop bundles, Docker image layers, and the standalone
PyInstaller binary. Those are separate artifact surfaces with separate
build steps; extending this module to cover them is a natural follow-up
once each of those pipelines is similarly wired to run in CI.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from tools.binary_extensions import has_binary_extension  # noqa: E402
from tools.rename_guard.scanner import (  # noqa: E402
    DEFAULT_ALLOWLIST,
    DEFAULT_BASELINE,
    DEFAULT_CONFIG,
    Occurrence,
    TERM_PATTERN,
    allowlist_match,
    is_excluded,
    load_json,
    to_report,
)


# A wheel's ``.data`` directory holds ``data_files`` (e.g. bundled locales,
# optional-mcp manifests) laid out as ``<name>-<version>.data/<category>/<rel>``
# where ``<rel>`` is the exact source-relative path the file lives at in the
# repo (e.g. ``locales/af.yaml``). Strip that wrapper so allowlist/baseline
# matching — keyed by source-relative path — still applies; without this,
# every bundled data file reports as a brand-new path with zero baseline
# credit, even though it's the identical, already-classified source content.
_WHEEL_DATA_PREFIX_RE = re.compile(r"^[^/]+\.data/[^/]+/")


def _normalize_wheel_path(path: str) -> str:
    return _WHEEL_DATA_PREFIX_RE.sub("", path, count=1)


def _iter_zip_members(archive_path: Path) -> list[tuple[str, bytes]]:
    members = []
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            members.append((_normalize_wheel_path(info.filename), zf.read(info)))
    return members


def _iter_tar_members(archive_path: Path) -> list[tuple[str, bytes]]:
    # An sdist tarball always wraps every file under a single top-level
    # ``<name>-<version>/`` directory (PEP 517/setuptools convention).
    # Strip it so matching is keyed by the same source-relative path used
    # by allowlist.json/baseline.json — otherwise literally every member
    # fails to match and reports as new.
    members = []
    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            rel_path = member.name.split("/", 1)[1] if "/" in member.name else member.name
            members.append((rel_path, extracted.read()))
    return members


def iter_archive_members(archive_path: Path) -> list[tuple[str, bytes]]:
    """Return ``(relative_path, raw_bytes)`` for every file in a wheel or sdist.

    Wheels are always zip archives (``.whl``); sdists are ``.tar.gz`` by PEP
    625 convention. Raises ``ValueError`` for anything else so a caller
    can't silently no-op on an unrecognized artifact type.
    """
    name = archive_path.name.lower()
    if name.endswith(".whl") or name.endswith(".zip"):
        return _iter_zip_members(archive_path)
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return _iter_tar_members(archive_path)
    raise ValueError(f"unrecognized artifact type: {archive_path}")


def scan_members(
    members: list[tuple[str, bytes]],
    config: dict,
    allowlist: list[dict],
    baseline: dict[str, int],
    today: date,
    surface_prefix: str = "",
) -> list[Occurrence]:
    """Apply the exact source-scanner classification to archive members.

    ``surface_prefix`` (e.g. ``"wheel:"``, ``"sdist:"``) is prepended to the
    reported path so a combined report can tell which artifact an
    occurrence came from without ambiguity, while ``baseline``/``allowlist``
    matching still uses the bare in-archive path (so entries can be shared
    with the source-scan config where the layout matches).
    """
    exclude_globs = config.get("exclude_globs", [])
    occurrences: list[Occurrence] = []
    baseline_seen: dict[str, int] = {}

    for rel_path, raw in members:
        if has_binary_extension(rel_path) or is_excluded(rel_path, exclude_globs):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in TERM_PATTERN.finditer(line):
                term = match.group(0)
                entry = allowlist_match(rel_path, term, allowlist, today)
                reported_path = f"{surface_prefix}{rel_path}"
                if entry is not None:
                    occurrences.append(Occurrence(
                        path=reported_path, line=lineno, surface=line.strip()[:200],
                        term=term, klass=entry["class"], reason=entry["reason"],
                    ))
                    continue
                baseline_seen[rel_path] = baseline_seen.get(rel_path, 0) + 1
                count_so_far = baseline_seen[rel_path]
                if count_so_far <= baseline.get(rel_path, 0):
                    klass, reason = "baseline", "pre-existing occurrence covered by frozen baseline"
                else:
                    klass = "new"
                    reason = "unclassified occurrence: not in allowlist, exceeds baseline"
                occurrences.append(Occurrence(
                    path=reported_path, line=lineno, surface=line.strip()[:200],
                    term=term, klass=klass, reason=reason,
                ))
    return occurrences


def scan_archive(
    archive_path: Path,
    config: dict,
    allowlist: list[dict],
    baseline: dict[str, int],
    today: date,
    surface_prefix: str = "",
) -> list[Occurrence]:
    return scan_members(
        iter_archive_members(archive_path), config, allowlist, baseline, today, surface_prefix,
    )


def build_distributions(out_dir: Path) -> tuple[Path, Path]:
    """Build the project's wheel + sdist into ``out_dir`` via ``uv build``.

    Mirrors the exact command ``upload_to_pypi.yml`` already runs
    (``uv build --sdist --wheel``) so the guard scans what is actually
    published, not a synthetic stand-in.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    subprocess.run(
        ["uv", "build", "--sdist", "--wheel", "-o", str(out_dir)],
        cwd=repo_root, check=True,
    )
    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    if not wheels:
        raise RuntimeError(f"uv build produced no .whl in {out_dir}")
    if not sdists:
        raise RuntimeError(f"uv build produced no .tar.gz in {out_dir}")
    return wheels[-1], sdists[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--wheel", type=Path, default=None,
        help="scan an already-built wheel instead of running uv build",
    )
    parser.add_argument(
        "--sdist", type=Path, default=None,
        help="scan an already-built sdist instead of running uv build",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    args = parser.parse_args(argv)

    config = load_json(args.config, {"exclude_globs": []})
    allowlist = load_json(args.allowlist, {"entries": []})["entries"]
    baseline = load_json(args.baseline, {"counts": {}})["counts"]
    today = date.today()

    if args.wheel and args.sdist:
        wheel_path, sdist_path = args.wheel, args.sdist
        tmpdir_ctx = None
    else:
        tmpdir_ctx = tempfile.TemporaryDirectory(prefix="rename-guard-artifact-")
        wheel_path, sdist_path = build_distributions(Path(tmpdir_ctx.name))

    try:
        occurrences = scan_archive(wheel_path, config, allowlist, baseline, today, "wheel:")
        occurrences += scan_archive(sdist_path, config, allowlist, baseline, today, "sdist:")
    finally:
        if tmpdir_ctx is not None:
            tmpdir_ctx.cleanup()

    report = to_report(occurrences)
    report["schema"] = "simplicio.rename-guard.artifact/v1"

    if args.json:
        import json
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for o in occurrences:
            if o.klass == "new":
                print(f"{o.path}:{o.line}: [{o.klass}] {o.term!r} — {o.reason}")
        print(f"rename-guard (artifacts): {report['new_count']} new unclassified occurrence(s) "
              f"out of {report['total']} total")

    return 1 if report["new_count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
