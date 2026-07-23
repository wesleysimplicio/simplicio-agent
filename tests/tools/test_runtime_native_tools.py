"""Runtime-first routing contracts for native Agent tools."""

from __future__ import annotations

import json
from unittest.mock import patch

from tools.runtime_native_tools import dispatch_native_tool
from tools.simplicio_transport import SimplicioTransport, TransportReceipt


class StubRuntime:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        value = self.values[name]
        if isinstance(value, TransportReceipt):
            return value
        return TransportReceipt.success("runtime_tool", value, transport="cli")


def test_read_file_is_adapted_to_runtime_file_read(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("TERMINAL_CWD", str(repo))
    runtime = StubRuntime({
        "simplicio_file_read": {
            "schema": "simplicio.read-result/v1",
            "content": "alpha\nbeta\n",
            "total_lines": 2,
            "file_size": 11,
            "truncated": False,
        }
    })

    result = dispatch_native_tool(
        "read_file",
        {"path": "note.txt", "offset": 2, "limit": 2},
        task_id="test",
        transport=runtime,
    )

    assert result.status == "executed"
    assert json.loads(result.result)["content"] == "2|alpha\n3|beta\n"
    name, args = runtime.calls[0]
    assert name == "simplicio_file_read"
    assert args["start"] == 2
    assert args["end"] == 3
    assert args["repo"] == str(repo)


def test_patch_replace_is_translated_to_runtime_edit(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "note.txt"
    path.write_text("old", encoding="utf-8")
    runtime = StubRuntime({"simplicio_edit": {"applied": True}})
    events = []
    monkeypatch.setattr(
        "tools.kernel_binding.emit_savings_event",
        lambda source, outcome, detail="": events.append((source, outcome, detail)),
    )
    monkeypatch.setattr(
        "tools.kernel_binding.evaluate_action_gate", lambda *args, **kwargs: None
    )

    result = dispatch_native_tool(
        "patch",
        {"mode": "replace", "path": str(path), "old_string": "old", "new_string": "new"},
        task_id="test",
        transport=runtime,
    )

    assert result.status == "executed"
    name, args = runtime.calls[0]
    assert name == "simplicio_edit"
    plan = json.loads(args["plan"])
    assert plan["file"] == str(path)
    assert plan["operations"] == [{"op": "replace", "find": "old", "with": "new"}]
    assert events == [("mechanical_edit", "applied", str(path))]


def test_write_existing_file_reads_and_edits_through_runtime(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "note.txt"
    path.write_text("old", encoding="utf-8")
    runtime = StubRuntime({
        "simplicio_file_read": {"content": "old", "total_lines": 1, "truncated": False},
        "simplicio_edit": {"applied": True},
    })
    monkeypatch.setattr(
        "tools.kernel_binding.evaluate_action_gate", lambda *args, **kwargs: None
    )

    result = dispatch_native_tool(
        "write_file",
        {"path": str(path), "content": "new"},
        task_id="test",
        transport=runtime,
    )

    assert result.status == "executed"
    assert [name for name, _args in runtime.calls] == ["simplicio_file_read", "simplicio_edit"]
    plan = json.loads(runtime.calls[1][1]["plan"])
    assert plan["operations"] == [{"op": "replace", "find": "old", "with": "new"}]


def test_patch_rejects_unacknowledged_runtime_edit(tmp_path, monkeypatch):
    path = tmp_path / "note.txt"
    path.write_text("old", encoding="utf-8")
    runtime = StubRuntime({"simplicio_edit": {}})
    monkeypatch.setattr(
        "tools.kernel_binding.evaluate_action_gate", lambda *args, **kwargs: None
    )

    result = dispatch_native_tool(
        "patch",
        {"mode": "replace", "path": str(path), "old_string": "old", "new_string": "new"},
        task_id="test",
        transport=runtime,
    )

    assert result.status == "gap"
    assert result.reason == "runtime_edit_unacknowledged"
    assert result.runtime_tool == "simplicio_edit"


def test_write_existing_file_rejects_unacknowledged_runtime_edit(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "note.txt"
    path.write_text("old", encoding="utf-8")
    runtime = StubRuntime({
        "simplicio_file_read": {"content": "old", "total_lines": 1, "truncated": False},
        "simplicio_edit": {"status": "ok-but-not-applied"},
    })
    monkeypatch.setattr(
        "tools.kernel_binding.evaluate_action_gate", lambda *args, **kwargs: None
    )

    result = dispatch_native_tool(
        "write_file",
        {"path": str(path), "content": "new"},
        task_id="test",
        transport=runtime,
    )

    assert result.status == "gap"
    assert result.reason == "runtime_edit_unacknowledged"
    assert path.read_text(encoding="utf-8") == "old"


def test_write_new_file_and_parent_directories_use_runtime_file_write(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("TERMINAL_CWD", str(repo))
    runtime = StubRuntime({"simplicio_file_write": {"applied": True}})
    monkeypatch.setattr(
        "tools.kernel_binding.evaluate_action_gate", lambda *args, **kwargs: None
    )

    result = dispatch_native_tool(
        "write_file",
        {"path": "nested/new.txt", "content": "new"},
        task_id="test",
        transport=runtime,
    )

    assert result.status == "executed"
    assert json.loads(result.result)["files_modified"] == [str(repo / "nested" / "new.txt")]
    assert runtime.calls == [(
        "simplicio_file_write",
        {
            "path": str(repo / "nested" / "new.txt"),
            "content": "new",
            "repo": str(repo),
            "create_parents": True,
        },
    )]


def test_runtime_file_write_cli_contract_is_explicit():
    import subprocess

    process = subprocess.CompletedProcess(
        ["simplicio"], 0, stdout='{"applied":true}', stderr=""
    )
    with patch("tools.simplicio_transport.subprocess.run", return_value=process) as run:
        result = SimplicioTransport(cli_bin="simplicio").call_tool(
            "simplicio_file_write",
            {"path": "/repo/nested/new.txt", "content": "new", "repo": "/repo", "create_parents": True},
        )

    assert result.ok is True
    assert result.transport == "cli"
    assert run.call_args.args[0] == [
        "simplicio", "file", "write", "/repo/nested/new.txt", "--content", "new", "--json",
        "--repo", "/repo", "--create-parents",
    ]


def test_tools_without_parity_report_a_gap_before_native_fallback():
    result = dispatch_native_tool("terminal", {"command": "echo hi"}, transport=StubRuntime({}))

    assert result.status == "gap"
    assert result.reason == "no_runtime_parity"


def test_mutating_native_tool_is_gated_before_runtime_edit(tmp_path, monkeypatch):
    path = tmp_path / "note.txt"
    path.write_text("old", encoding="utf-8")
    runtime = StubRuntime({"simplicio_edit": {"applied": True}})
    gate_calls = []

    def deny(action, **kwargs):
        gate_calls.append((action, kwargs))
        return {"approved": False, "message": "blocked by runtime gate"}

    monkeypatch.setattr("tools.kernel_binding.evaluate_action_gate", deny)

    result = dispatch_native_tool(
        "patch",
        {"mode": "replace", "path": str(path), "old_string": "old", "new_string": "new"},
        task_id="test-task",
        transport=runtime,
    )

    assert result.status == "blocked"
    assert result.runtime_tool == "simplicio_gate"
    assert json.loads(result.result)["error"] == "blocked by runtime gate"
    assert runtime.calls == []
    assert gate_calls == [
        (
            f"patch {path}",
            {
                "pattern_key": "patch",
                "description": "native patch mutation",
                "session_key": "test-task",
            },
        )
    ]


def test_transport_uses_dynamic_runtime_mcp_tool_name_when_cli_is_unavailable():
    calls = []
    transport = SimplicioTransport(
        cli_bin="missing-simplicio",
        mcp_call=lambda operation, args: calls.append((operation, args)) or {"ok": True},
    )

    result = transport.call_tool("simplicio_file_read", {"path": "note.txt", "repo": "."})

    assert result.ok is True
    assert result.transport == "mcp"
    assert calls == [
        ("runtime_tool", {"name": "simplicio_file_read", "arguments": {"path": "note.txt", "repo": "."}})
    ]


def test_transport_uses_runtime_cli_before_mcp_for_native_tool():
    import subprocess
    from unittest.mock import patch

    process = subprocess.CompletedProcess(
        ["simplicio"], 0, stdout='{"content":"x","total_lines":1}', stderr=""
    )
    with patch("tools.simplicio_transport.subprocess.run", return_value=process) as run:
        result = SimplicioTransport(cli_bin="simplicio").call_tool(
            "simplicio_file_read", {"path": "/repo/note.txt", "repo": "/repo", "start": 1, "end": 1}
        )

    assert result.ok is True
    assert result.transport == "cli"
    assert run.call_args.args[0] == [
        "simplicio", "file", "read", "/repo/note.txt", "--json",
        "--repo", "/repo", "--start", "1", "--end", "1",
    ]


def test_session_search_uses_cli_for_supported_shape_and_json_output():
    import subprocess

    process = subprocess.CompletedProcess(
        ["simplicio"], 0, stdout='{"success":true,"mode":"discover","results":[]}', stderr=""
    )
    with patch("tools.simplicio_transport.subprocess.run", return_value=process) as run:
        result = SimplicioTransport(cli_bin="simplicio").call_tool(
            "simplicio_session_search",
            {"query": "runtime parity", "limit": 5, "profile": "work"},
        )

    assert result.ok is True
    assert result.transport == "cli"
    assert run.call_args.args[0] == [
        "simplicio", "session", "search", "runtime parity",
        "--limit", "5", "--profile", "work", "--json",
    ]


def test_session_search_keeps_scroll_on_mcp_when_cli_cannot_preserve_shape():
    calls = []
    transport = SimplicioTransport(
        cli_bin="simplicio",
        mcp_call=lambda operation, args: calls.append((operation, args)) or {
            "success": True, "mode": "scroll", "messages": []
        },
    )

    with patch("tools.simplicio_transport.subprocess.run") as run:
        result = transport.call_tool(
            "simplicio_session_search",
            {"session_id": "session-1", "around_message_id": 42, "window": 5},
        )

    assert result.ok is True
    assert result.transport == "mcp"
    run.assert_not_called()
    assert calls == [(
        "runtime_tool",
        {
            "name": "simplicio_session_search",
            "arguments": {"session_id": "session-1", "around_message_id": 42, "window": 5},
        },
    )]
