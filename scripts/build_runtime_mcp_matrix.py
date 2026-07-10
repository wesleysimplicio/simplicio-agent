#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hermes_cli.runtime_mcp_matrix import (
    build_runtime_mcp_matrix,
    coverage_summary,
    matrix_as_dict,
    render_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an offline CLI×MCP coverage matrix from Simplicio Runtime snapshots."
    )
    parser.add_argument("--help-file", required=True, type=Path)
    parser.add_argument("--tools-file", required=True, type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()

    help_text = args.help_file.read_text(encoding="utf-8")
    tools_payload = args.tools_file.read_text(encoding="utf-8")
    rows = build_runtime_mcp_matrix(help_text, tools_payload)
    if args.format == "markdown":
        print(render_markdown(rows))
        return 0

    print(
        json.dumps(
            {
                "summary": coverage_summary(rows),
                "rows": matrix_as_dict(rows),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
