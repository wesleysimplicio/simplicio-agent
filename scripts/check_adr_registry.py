"""Fail when ADR filenames, numbering or generated index drift."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.adr_registry import iter_adrs, validate
except ImportError:  # pragma: no cover - direct script execution
    from adr_registry import iter_adrs, validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("docs/architecture"))
    parser.add_argument(
        "--index", type=Path, default=Path("docs/architecture/INDEX.md")
    )
    args = parser.parse_args()
    errors = validate(iter_adrs(args.root), require_index=args.index)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"ADR registry OK: {len(iter_adrs(args.root))} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
