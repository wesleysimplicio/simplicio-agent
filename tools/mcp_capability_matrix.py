"""Build a deterministic CLI/MCP capability matrix from live captures."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_COMMAND_RE = re.compile(r"^\s*(simplicio(?:-agent)?(?:\s+[^\s<\[]+)?)\s{2,}")


def parse_cli_commands(help_text: str) -> list[str]:
    """Extract command invocations from ``simplicio --help`` output."""
    commands = {match.group(1).strip() for line in help_text.splitlines() if (match := _COMMAND_RE.match(line))}
    return sorted(commands)


def parse_mcp_tools(payload: str | bytes | dict[str, Any] | list[Any]) -> list[str]:
    """Extract tool names from MCP ``tools/list`` JSON or JSONL output."""
    if isinstance(payload, (str, bytes)):
        text = payload.decode() if isinstance(payload, bytes) else payload
        try:
            value: Any = json.loads(text)
        except json.JSONDecodeError:
            value = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        value = payload

    if isinstance(value, list):
        messages = value
    else:
        messages = [value]
    tools: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            continue
        candidates = message.get("tools")
        if candidates is None and isinstance(message.get("result"), dict):
            candidates = message["result"].get("tools")
        if not isinstance(candidates, list):
            continue
        tools.update(item["name"] for item in candidates if isinstance(item, dict) and isinstance(item.get("name"), str))
    return sorted(tools)


def build_matrix(commands: list[str], tools: list[str]) -> dict[str, Any]:
    """Return a stable matrix and explicit provenance for captured surfaces."""
    tool_set = set(tools)
    rows = []
    for command in sorted(set(commands)):
        leaf = command.split()[-1]
        exact = leaf in tool_set or command.replace(" ", "_") in tool_set
        rows.append(
            {
                "command": command,
                "mcp_tool": leaf if leaf in tool_set else (command.replace(" ", "_") if exact else None),
                "transport": "mcp" if exact else "cli-fallback",
                "gap": not exact,
            }
        )
    return {
        "schema": "simplicio.agent.mcp-capability-matrix.v1",
        "source": {"cli": "simplicio --help", "mcp": "simplicio serve --mcp --stdio tools/list"},
        "commands": rows,
        "mcp_tools": sorted(tool_set),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-help", type=Path, required=True)
    parser.add_argument("--mcp-tools", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matrix = build_matrix(parse_cli_commands(args.cli_help.read_text(encoding="utf-8")), parse_mcp_tools(args.mcp_tools.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
