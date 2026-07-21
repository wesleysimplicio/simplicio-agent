"""The common dispatcher gives native execution tools a Runtime first turn."""

from __future__ import annotations

from tools.runtime_native_tools import RuntimeNativeDispatch


def test_handle_function_call_returns_runtime_result_before_registry(monkeypatch):
    import model_tools

    monkeypatch.setattr(
        "tools.runtime_native_tools.dispatch_native_tool",
        lambda *args, **kwargs: RuntimeNativeDispatch(
            "read_file", "executed", result='{"runtime": true}', runtime_tool="simplicio_file_read"
        ),
    )
    registry_called = []
    monkeypatch.setattr(
        model_tools.registry,
        "dispatch",
        lambda *args, **kwargs: registry_called.append((args, kwargs)) or '{"native": true}',
    )

    result = model_tools.handle_function_call(
        "read_file",
        {"path": "note.txt"},
        task_id="task-1",
        skip_pre_tool_call_hook=True,
    )

    assert result == '{"runtime": true}'
    assert registry_called == []


def test_handle_function_call_keeps_native_recovery_after_runtime_gap(monkeypatch):
    import model_tools

    monkeypatch.setattr(
        "tools.runtime_native_tools.dispatch_native_tool",
        lambda *args, **kwargs: RuntimeNativeDispatch(
            "terminal", "gap", reason="no_runtime_parity"
        ),
    )
    registry_called = []
    monkeypatch.setattr(
        model_tools.registry,
        "dispatch",
        lambda *args, **kwargs: registry_called.append((args, kwargs)) or '{"native": true}',
    )

    result = model_tools.handle_function_call(
        "terminal",
        {"command": "echo hi"},
        task_id="task-1",
        skip_pre_tool_call_hook=True,
    )

    assert result == '{"native": true}'
    assert registry_called and registry_called[0][0][0] == "terminal"
