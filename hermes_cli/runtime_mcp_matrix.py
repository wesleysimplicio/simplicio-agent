from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

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

MATRIX_SCHEMA = "simplicio.runtime-mcp-parity"
MATRIX_VERSION = 1
EVIDENCE_KINDS = frozenset({"live", "snapshot"})
ROUTES = frozenset({"mcp", "cli_fallback", "gap"})
DEFAULT_MATRIX_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "capabilities"
    / "runtime-mcp-parity.v1.json"
)


@dataclass(frozen=True)
class CoverageRow:
    command: str
    normalized_tool: str
    status: str
    priority: str
    tool_name: str | None


@dataclass(frozen=True)
class Evidence:
    """Provenance for one side of the parity matrix.

    ``live`` means a command was queried during the current run.  ``snapshot``
    means the value comes from a checked-in fixture or checked-in generated
    documentation and must not be presented as a live probe.
    """

    surface: str
    kind: str
    source: str
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.surface.strip() or not self.source.strip():
            raise ValueError("evidence surface and source must be non-empty")
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(f"unsupported evidence kind: {self.kind!r}")


@dataclass(frozen=True)
class ParityRow:
    """One bounded capability and its deterministic route."""

    command: str
    mcp_tool: str | None
    cli_fallback: str | None
    route: str
    evidence: tuple[str, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.command.strip():
            raise ValueError("capability command must be non-empty")
        if self.route not in ROUTES:
            raise ValueError(f"unsupported parity route: {self.route!r}")
        if self.route == "mcp" and not self.mcp_tool:
            raise ValueError("mcp route requires mcp_tool")
        if self.route == "cli_fallback" and not self.cli_fallback:
            raise ValueError("cli_fallback route requires cli_fallback")
        if self.route == "gap" and (self.mcp_tool or self.cli_fallback):
            raise ValueError("gap route cannot claim MCP or CLI coverage")


@dataclass(frozen=True)
class RouteDecision:
    """The stable result of routing a known command."""

    command: str
    route: str
    target: str | None
    reason: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class MatrixStatus:
    """Deterministic summary of a versioned parity matrix."""

    schema: str
    version: int
    commands_total: int
    mcp_routes: int
    cli_fallback_routes: int
    gaps: int
    missing_commands: tuple[str, ...]
    missing_tools: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing_commands and not self.missing_tools and self.gaps == 0

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {"ready": self.ready}


@dataclass(frozen=True)
class CapabilityMatrix:
    """Validated, versioned authority for the bounded parity slice."""

    schema: str
    version: int
    scope: str
    evidence: tuple[Evidence, ...]
    known_commands: tuple[str, ...]
    known_tools: tuple[str, ...]
    rows: tuple[ParityRow, ...]

    def __post_init__(self) -> None:
        if self.schema != MATRIX_SCHEMA or self.version != MATRIX_VERSION:
            raise ValueError(
                f"unsupported matrix contract: {self.schema!r} v{self.version}"
            )
        if not self.scope.strip():
            raise ValueError("matrix scope must be non-empty")
        if len(set(self.known_commands)) != len(self.known_commands):
            raise ValueError("known_commands must be unique")
        if len(set(self.known_tools)) != len(self.known_tools):
            raise ValueError("known_tools must be unique")
        if len({row.command for row in self.rows}) != len(self.rows):
            raise ValueError("matrix rows must contain one row per command")
        row_commands = {row.command for row in self.rows}
        missing_rows = set(self.known_commands) - row_commands
        if missing_rows:
            raise ValueError(
                "matrix is missing known commands: " + ", ".join(sorted(missing_rows))
            )
        row_tools = {row.mcp_tool for row in self.rows if row.mcp_tool}
        missing_tools = set(self.known_tools) - row_tools
        if missing_tools:
            raise ValueError(
                "matrix is missing known tools: " + ", ".join(sorted(missing_tools))
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CapabilityMatrix":
        """Load and validate the checked-in JSON authority."""

        evidence = tuple(
            Evidence(
                surface=str(item["surface"]),
                kind=str(item["kind"]),
                source=str(item["source"]),
                version=str(item["version"]) if item.get("version") is not None else None,
            )
            for item in _mapping_list(payload, "evidence")
        )
        rows = tuple(
            ParityRow(
                command=str(item["command"]),
                mcp_tool=_optional_string(item.get("mcp_tool")),
                cli_fallback=_optional_string(item.get("cli_fallback")),
                route=str(item["route"]),
                evidence=tuple(str(value) for value in item.get("evidence", [])),
                notes=str(item.get("notes", "")),
            )
            for item in _mapping_list(payload, "rows")
        )
        matrix = cls(
            schema=str(payload.get("schema", "")),
            version=int(payload.get("version", -1)),
            scope=str(payload.get("scope", "")),
            evidence=evidence,
            known_commands=tuple(str(value) for value in _sequence(payload, "known_commands")),
            known_tools=tuple(str(value) for value in _sequence(payload, "known_tools")),
            rows=rows,
        )
        evidence_ids = {item.surface for item in matrix.evidence}
        unknown_evidence = {
            item for row in matrix.rows for item in row.evidence if item not in evidence_ids
        }
        if unknown_evidence:
            raise ValueError(
                "rows refer to unknown evidence: " + ", ".join(sorted(unknown_evidence))
            )
        return matrix

    @classmethod
    def from_json(cls, path: str | Path = DEFAULT_MATRIX_PATH) -> "CapabilityMatrix":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def row_for(self, command: str) -> ParityRow | None:
        normalized = command.strip().lower()
        return next(
            (row for row in self.rows if row.command.lower() == normalized), None
        )

    def route(self, command: str, *, mcp_tools: Iterable[str] | None = None) -> RouteDecision:
        """Choose MCP first, then the declared CLI fallback, never by scoring."""

        row = self.row_for(command)
        if row is None:
            return RouteDecision(command, "gap", None, "unknown_command", ())
        available_tools = set(mcp_tools) if mcp_tools is not None else set(self.known_tools)
        if row.mcp_tool and row.mcp_tool in available_tools:
            return RouteDecision(row.command, "mcp", row.mcp_tool, "mcp_available", row.evidence)
        if row.cli_fallback:
            reason = "mcp_unavailable_cli_fallback" if row.mcp_tool else "cli_fallback_declared"
            return RouteDecision(row.command, "cli_fallback", row.cli_fallback, reason, row.evidence)
        return RouteDecision(row.command, "gap", None, "no_supported_route", row.evidence)

    def status(self, *, observed_commands: Iterable[str] | None = None,
               observed_tools: Iterable[str] | None = None) -> MatrixStatus:
        commands = tuple(observed_commands) if observed_commands is not None else self.known_commands
        tools = tuple(observed_tools) if observed_tools is not None else self.known_tools
        counts = {route: 0 for route in ROUTES}
        for row in self.rows:
            counts[self.route(row.command, mcp_tools=tools).route] += 1
        return MatrixStatus(
            schema=self.schema,
            version=self.version,
            commands_total=len(self.rows),
            mcp_routes=counts["mcp"],
            cli_fallback_routes=counts["cli_fallback"],
            gaps=counts["gap"],
            missing_commands=tuple(missing_known_commands(self.known_commands, commands)),
            missing_tools=tuple(missing_known_tools(self.known_tools, tools)),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "scope": self.scope,
            "evidence": [asdict(item) for item in self.evidence],
            "known_commands": list(self.known_commands),
            "known_tools": list(self.known_tools),
            "rows": [asdict(item) for item in self.rows],
        }


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


def missing_known_commands(
    known_commands: Iterable[str], observed_commands: Iterable[str]
) -> list[str]:
    """Return known CLI commands absent from a help/snapshot observation."""

    observed = {item.strip().lower() for item in observed_commands}
    return sorted({item.strip().lower() for item in known_commands} - observed)


def missing_known_tools(known_tools: Iterable[str], observed_tools: Iterable[str]) -> list[str]:
    """Return known MCP tools absent from a tools/list or snapshot observation."""

    observed = {item.strip() for item in observed_tools}
    return sorted(set(known_tools) - observed)


def load_capability_matrix(path: str | Path = DEFAULT_MATRIX_PATH) -> CapabilityMatrix:
    """Load the repository's authoritative bounded parity matrix."""

    return CapabilityMatrix.from_json(path)


def _mapping_list(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{key} must be a list of objects")
    return list(value)


def _sequence(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("optional matrix values must be non-empty strings or null")
    return value
