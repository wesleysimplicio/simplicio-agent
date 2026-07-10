from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable

HIGH_PRIORITY_COMMANDS = {
    "doctor",
    "handoff",
    "inspect",
    "intake",
    "map",
    "memory",
    "plan",
    "recall",
    "run",
    "skills",
    "task-contract",
    "validate",
}

CLI_FALLBACK_COMMANDS = {
    "help",
    "serve",
    "version",
}

COMMAND_TOOL_ALIASES = {
    "task-contract": "task_contract",
}


@dataclass(frozen=True)
class CoverageRow:
    command: str
    normalized_tool: str
    status: str
    priority: str
    tool_name: str | None


def parse_runtime_help_commands(help_text: str) -> list[str]:
    commands: list[str] = []
    in_commands = False
    for raw_line in help_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_commands:
                continue
            continue
        if stripped.endswith(":") and stripped.lower() in {
            "commands:",
            "available commands:",
            "subcommands:",
        }:
            in_commands = True
            continue
        if not in_commands:
            continue
        if re.match(r"^[A-Z][A-Za-z /-]+:$", stripped):
            break
        if stripped.lower().startswith(("options:", "arguments:", "flags:", "usage:")):
            break
        match = re.match(r"^\s{2,}([a-z0-9][a-z0-9-]*)\b", line, flags=re.IGNORECASE)
        if not match:
            continue
        command = match.group(1).lower()
        if command not in commands:
            commands.append(command)
    return commands


def parse_mcp_tool_names(payload: str) -> set[str]:
    names = _parse_tool_names_json(payload)
    if names:
        return names
    names = set()
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        names.update(_parse_tool_names_json(line))
    if names:
        return names
    return set(re.findall(r'"name"\s*:\s*"([^"]+)"', payload))


def build_runtime_mcp_matrix(
    help_text: str,
    tools_payload: str,
    *,
    high_priority_commands: Iterable[str] | None = None,
    cli_fallback_commands: Iterable[str] | None = None,
) -> list[CoverageRow]:
    commands = parse_runtime_help_commands(help_text)
    tool_names = parse_mcp_tool_names(tools_payload)
    high_priority = {item.lower() for item in (high_priority_commands or HIGH_PRIORITY_COMMANDS)}
    cli_fallback = {item.lower() for item in (cli_fallback_commands or CLI_FALLBACK_COMMANDS)}
    rows: list[CoverageRow] = []
    for command in commands:
        normalized_tool = normalize_runtime_tool_name(command)
        if normalized_tool in tool_names:
            status = "mcp_tool"
            tool_name = normalized_tool
        elif command in cli_fallback:
            status = "cli_fallback"
            tool_name = None
        else:
            status = "gap"
            tool_name = None
        priority = "high" if command in high_priority else "normal"
        rows.append(
            CoverageRow(
                command=command,
                normalized_tool=normalized_tool,
                status=status,
                priority=priority,
                tool_name=tool_name,
            )
        )
    return rows


def coverage_summary(rows: Iterable[CoverageRow]) -> dict[str, object]:
    items = list(rows)
    counts = {"mcp_tool": 0, "cli_fallback": 0, "gap": 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    total = len(items)
    covered = counts["mcp_tool"]
    if total == 0:
        status = "fallback_required"
    elif counts["gap"] == 0:
        status = "mcp_complete"
    elif covered == 0:
        status = "fallback_required"
    else:
        status = "mcp_partial"
    return {
        "status": status,
        "counts": counts,
        "commands_total": total,
    }


def matrix_as_dict(rows: Iterable[CoverageRow]) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]


def render_markdown(rows: Iterable[CoverageRow]) -> str:
    items = list(rows)
    header = "| Command | MCP tool | Status | Priority |\n|---|---|---|---|"
    body = [
        f"| `{row.command}` | `{row.tool_name or row.normalized_tool}` | {row.status} | {row.priority} |"
        for row in items
    ]
    summary = coverage_summary(items)
    return "\n".join(
        [
            header,
            *body,
            "",
            f"Overall status: **{summary['status']}**",
        ]
    )


def normalize_runtime_tool_name(command: str) -> str:
    suffix = COMMAND_TOOL_ALIASES.get(command, command.replace("-", "_"))
    return f"simplicio_{suffix}"


def _parse_tool_names_json(payload: str) -> set[str]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return set()
    names: set[str] = set()
    _collect_tool_names(parsed, names)
    return names


def _collect_tool_names(node: object, names: set[str]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("tools"), list):
            for item in node["tools"]:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        names.add(name)
        for value in node.values():
            _collect_tool_names(value, names)
        return
    if isinstance(node, list):
        for item in node:
            _collect_tool_names(item, names)
