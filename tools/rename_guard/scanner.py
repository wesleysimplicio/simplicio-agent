#!/usr/bin/env python3
"""Deterministic branding-regression guard (issue #194).

Scans git-tracked text files for old-brand tokens and reports every
occurrence as either:

- ``allowed``   — matched by a live (non-expired) allowlist entry, tagged
                  with its ``class`` (KEEP_INTERNAL/credit/alias/upstream/
                  fixture) and ``reason``.
- ``baseline``  — not allowlisted, but already present in the frozen
                  baseline snapshot (pre-existing debt, not a regression).
- ``new``       — neither allowlisted nor baselined: a genuine new
                  unclassified occurrence. Fails the guard.

The baseline is a ratchet: this scanner never *writes* it, so a PR cannot
silently grow the baseline to hide a regression — bumping it is a
reviewable, human-authored diff (or ``bootstrap``, run explicitly, never
part of the checker's own gate path).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from tools.binary_extensions import has_binary_extension  # noqa: E402

GUARD_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = GUARD_DIR / "config.json"
DEFAULT_ALLOWLIST = GUARD_DIR / "allowlist.json"
DEFAULT_BASELINE = GUARD_DIR / "baseline.json"

# Case/spacing/hyphen/underscore variants of the retired brand token.
TERM_PATTERN = re.compile(r"h[\s._-]*e[\s._-]*r[\s._-]*m[\s._-]*e[\s._-]*s", re.IGNORECASE)


@dataclass(frozen=True)
class Occurrence:
    path: str
    line: int
    surface: str
    term: str
    klass: str
    reason: str


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line]


def is_excluded(path: str, exclude_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in exclude_globs)


def allowlist_match(path: str, term: str, entries: list[dict], today: date) -> dict | None:
    for entry in entries:
        if not fnmatch.fnmatch(path, entry["path_glob"]):
            continue
        if entry.get("term") and entry["term"].lower() != term.lower():
            continue
        expiry = entry.get("expiry")
        if expiry:
            try:
                if date.fromisoformat(expiry) < today:
                    continue  # expired: falls through to new/baseline classification
            except ValueError:
                continue
        return entry
    return None


def scan(root: Path, config: dict, allowlist: list[dict], baseline: dict[str, int],
          today: date) -> list[Occurrence]:
    exclude_globs = config.get("exclude_globs", [])
    occurrences: list[Occurrence] = []
    baseline_seen: dict[str, int] = {}

    for rel_path in tracked_files(root):
        if has_binary_extension(rel_path) or is_excluded(rel_path, exclude_globs):
            continue
        abs_path = root / rel_path
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in TERM_PATTERN.finditer(line):
                term = match.group(0)
                entry = allowlist_match(rel_path, term, allowlist, today)
                if entry is not None:
                    occurrences.append(Occurrence(
                        path=rel_path, line=lineno, surface=line.strip()[:200],
                        term=term, klass=entry["class"], reason=entry["reason"],
                    ))
                    continue
                baseline_seen[rel_path] = baseline_seen.get(rel_path, 0) + 1
                count_so_far = baseline_seen[rel_path]
                if count_so_far <= baseline.get(rel_path, 0):
                    klass = "baseline"
                    reason = "pre-existing occurrence covered by frozen baseline"
                else:
                    klass = "new"
                    reason = "unclassified occurrence: not in allowlist, exceeds baseline"
                occurrences.append(Occurrence(
                    path=rel_path, line=lineno, surface=line.strip()[:200],
                    term=term, klass=klass, reason=reason,
                ))
    return occurrences


def to_report(occurrences: list[Occurrence]) -> dict:
    return {
        "schema": "simplicio.rename-guard/v1",
        "total": len(occurrences),
        "new_count": sum(1 for o in occurrences if o.klass == "new"),
        "occurrences": [
            {
                "path": o.path,
                "line": o.line,
                "surface": o.surface,
                "term": o.term,
                "class": o.klass,
                "reason": o.reason,
            }
            for o in occurrences
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    args = parser.parse_args(argv)

    config = load_json(args.config, {"exclude_globs": []})
    allowlist = load_json(args.allowlist, {"entries": []})["entries"]
    baseline = load_json(args.baseline, {"counts": {}})["counts"]

    occurrences = scan(args.root, config, allowlist, baseline, date.today())
    report = to_report(occurrences)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for o in occurrences:
            if o.klass == "new":
                print(f"{o.path}:{o.line}: [{o.klass}] {o.term!r} — {o.reason}")
        print(f"rename-guard: {report['new_count']} new unclassified occurrence(s) "
              f"out of {report['total']} total")

    return 1 if report["new_count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
