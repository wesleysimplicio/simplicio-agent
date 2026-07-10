from __future__ import annotations

from hermes_cli.runtime_mcp_matrix import (
    build_runtime_mcp_matrix,
    coverage_summary,
    parse_mcp_tool_names,
    parse_runtime_help_commands,
    render_markdown,
)


def test_parse_runtime_help_commands_reads_commands_block():
    help_text = """
Simplicio Runtime

Usage: simplicio [COMMAND]

Commands:
  map             Build repo map
  intake          Compile task intake
  run             Execute task
  task-contract   Compile contract
  serve           Start stdio/http services
  version         Print version

Options:
  -h, --help      Print help
"""
    assert parse_runtime_help_commands(help_text) == [
        "map",
        "intake",
        "run",
        "task-contract",
        "serve",
        "version",
    ]


def test_parse_mcp_tool_names_reads_jsonrpc_tools_list():
    payload = """
{"jsonrpc":"2.0","id":1,"result":{"tools":[
  {"name":"simplicio_map","description":"Map repo"},
  {"name":"simplicio_run","description":"Run task"},
  {"name":"simplicio_task_contract","description":"Compile contract"}
]}}
"""
    assert parse_mcp_tool_names(payload) == {
        "simplicio_map",
        "simplicio_run",
        "simplicio_task_contract",
    }


def test_build_runtime_mcp_matrix_classifies_mcp_fallback_and_gap():
    help_text = """
Commands:
  map             Build repo map
  intake          Compile task intake
  run             Execute task
  task-contract   Compile contract
  serve           Start MCP server
  version         Print version
"""
    payload = """
{"result":{"tools":[
  {"name":"simplicio_map"},
  {"name":"simplicio_run"},
  {"name":"simplicio_task_contract"}
]}}
"""
    rows = build_runtime_mcp_matrix(help_text, payload)
    by_command = {row.command: row for row in rows}

    assert by_command["map"].status == "mcp_tool"
    assert by_command["run"].status == "mcp_tool"
    assert by_command["task-contract"].status == "mcp_tool"
    assert by_command["serve"].status == "cli_fallback"
    assert by_command["version"].status == "cli_fallback"
    assert by_command["intake"].status == "gap"
    assert by_command["intake"].priority == "high"

    summary = coverage_summary(rows)
    assert summary["status"] == "mcp_partial"
    assert summary["counts"] == {"mcp_tool": 3, "cli_fallback": 2, "gap": 1}


def test_render_markdown_includes_summary_line():
    help_text = """
Commands:
  map     Build repo map
"""
    payload = '{"result":{"tools":[{"name":"simplicio_map"}]}}'
    rows = build_runtime_mcp_matrix(help_text, payload)
    rendered = render_markdown(rows)
    assert "| `map` | `simplicio_map` | mcp_tool | high |" in rendered
    assert "Overall status: **mcp_complete**" in rendered
