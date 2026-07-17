"""Fail if a doc/skill states a routing hierarchy that contradicts AGENTS.md.

Issue #212: the repo used to carry both "CLI-first, MCP-fallback" (the
canonical ADR-0010 decision recorded in AGENTS.md § Tool routing) and an
older "Hermes-native tools first" instruction for orientation/reading/
searching. Both claimed to be authoritative for the same decision, which is
ambiguous for anyone (human or agent) reading the docs. This script is a
regression guard: it fails if any of the known-conflicting phrases reappear
outside of `archive/` (frozen historical snapshot) or `CHANGELOG.md`
(historical record, not active guidance).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CONFLICTING_PATTERNS = [
    re.compile(r"Hermes-native (tools|orientation) first", re.IGNORECASE),
]

EXCLUDED_DIR_NAMES = {".git", "archive", "node_modules", "__pycache__"}
EXCLUDED_FILES = {"CHANGELOG.md"}


def _is_excluded(path: Path, root: Path) -> bool:
    if path.name in EXCLUDED_FILES:
        return True
    for part in path.relative_to(root).parts[:-1]:
        if part in EXCLUDED_DIR_NAMES:
            return True
    return False


def find_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.md")):
        if _is_excluded(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in CONFLICTING_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"{path.relative_to(root)}:{lineno}: conflicts with AGENTS.md"
                        f" Tool routing (ADR-0010, issue #212): {line.strip()!r}"
                    )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root to scan")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = find_violations(root)
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(
            f"routing docs check: {len(violations)} conflicting phrase(s) found",
            file=sys.stderr,
        )
        return 1

    print("routing docs check OK: no conflicting Hermes-native-first phrasing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
