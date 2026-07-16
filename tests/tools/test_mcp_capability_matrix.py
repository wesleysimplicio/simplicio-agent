from tools.mcp_capability_matrix import build_matrix, parse_cli_commands, parse_mcp_tools


def test_parse_cli_commands_extracts_invocations_and_deduplicates():
    text = """
      simplicio doctor       inspect health
      simplicio serve        start runtime
      simplicio doctor       inspect health
    """
    assert parse_cli_commands(text) == ["simplicio doctor", "simplicio serve"]


def test_parse_mcp_tools_accepts_result_and_jsonl_payloads():
    assert parse_mcp_tools('{"result":{"tools":[{"name":"doctor"},{"name":"serve"}]}}') == ["doctor", "serve"]
    assert parse_mcp_tools('{"tools":[{"name":"memory"}]}\n{"tools":[{"name":"doctor"}]}') == ["doctor", "memory"]


def test_build_matrix_marks_mcp_exact_and_cli_fallback_rows():
    matrix = build_matrix(["simplicio doctor", "simplicio serve"], ["doctor"])
    assert matrix["schema"].endswith(".v1")
    assert matrix["commands"] == [
        {"command": "simplicio doctor", "mcp_tool": "doctor", "transport": "mcp", "gap": False},
        {"command": "simplicio serve", "mcp_tool": None, "transport": "cli-fallback", "gap": True},
    ]
