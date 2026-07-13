#!/usr/bin/env python3
"""Freeze today's non-allowlisted occurrences into baseline.json.

This is a deliberate, human-invoked action — NOT part of the guard's own
gate path (``scanner.py`` never calls this). Bumping the baseline is a
reviewable diff; the guard itself only ever reads it and never grows it.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from tools.rename_guard.scanner import (
    DEFAULT_ALLOWLIST,
    DEFAULT_BASELINE,
    DEFAULT_CONFIG,
    allowlist_match,
    has_binary_extension,
    is_excluded,
    load_json,
    tracked_files,
    TERM_PATTERN,
)


def count_unclassified(root: Path, config: dict, allowlist: list[dict], today: date) -> Counter:
    counts: Counter = Counter()
    exclude_globs = config.get("exclude_globs", [])
    for rel_path in tracked_files(root):
        if has_binary_extension(rel_path) or is_excluded(rel_path, exclude_globs):
            continue
        abs_path = root / rel_path
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in text.splitlines():
            for match in TERM_PATTERN.finditer(line):
                if allowlist_match(rel_path, match.group(0), allowlist, today) is not None:
                    continue
                counts[rel_path] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--out", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args(argv)

    config = load_json(args.config, {"exclude_globs": []})
    allowlist = load_json(args.allowlist, {"entries": []})["entries"]
    counts = count_unclassified(args.root, config, allowlist, date.today())

    args.out.write_text(
        json.dumps(
            {
                "schema": "simplicio.rename-guard.baseline/v1",
                "generated_at": date.today().isoformat(),
                "counts": dict(sorted(counts.items())),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"baseline written: {len(counts)} file(s), {sum(counts.values())} occurrence(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
