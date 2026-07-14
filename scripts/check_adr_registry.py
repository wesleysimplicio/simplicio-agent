"""Fail when ADR filenames, numbering or generated index drift."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.adr_registry import iter_adrs, validate
    from scripts.gen_adr_index import render
except ImportError:  # pragma: no cover - direct script execution
    from adr_registry import iter_adrs, validate
    from gen_adr_index import render


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("docs/architecture"))
    parser.add_argument(
        "--index", type=Path, default=Path("docs/architecture/INDEX.md")
    )
    args = parser.parse_args()
    entries = iter_adrs(args.root)
    errors = validate(entries, require_index=args.index)
    if not errors and args.index.read_text(encoding="utf-8") != render(entries):
        errors.append("index is stale; run python scripts/gen_adr_index.py")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"ADR registry OK: {len(entries)} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
