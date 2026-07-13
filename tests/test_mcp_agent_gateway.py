from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import mcp_agent_gateway as gateway


def test_rank_capabilities_returns_compact_helo_metadata(tmp_path, monkeypatch):
    calls = []
    payload = {
        "selected": [
            {
                "reason": "task match",
                "capability": {
                    "id": "deterministic-shell-checks",
                    "kind": "validator",
                    "pack": "tdd-verification",
                    "status": "installed",
                    "example_invocations": ["simplicio validate task --json"],
                    "large_body": "must not leak",
                },
            }
        ]
    }

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout='{"schema":"simplicio.progress/v1"}\n' + json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(gateway, "_binary", lambda name: f"/bin/{name}")
    monkeypatch.setattr(gateway.subprocess, "run", fake_run)

    result = gateway.rank_capabilities("run tests", workdir=str(tmp_path))

    assert result["success"] is True
    assert result["mode"] == "fast:fast"
    assert result["selected"] == [
        {
            "id": "deterministic-shell-checks",
            "kind": "validator",
            "pack": "tdd-verification",
            "status": "installed",
            "reason": "task match",
            "examples": ["simplicio validate task --json"],
        }
    ]
    assert calls[0][0][:4] == [
        "/bin/simplicio",
        "capabilities",
        "rank",
        "run tests",
    ]


def test_invoke_agent_is_always_yolo_and_fast_fast(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "rank_capabilities",
        lambda *args, **kwargs: {
            "success": True,
            "selected": [{"id": "file/search/patch"}],
        },
    )
    monkeypatch.setattr(gateway, "_binary", lambda name: f"/bin/{name}")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="MEASURED| done\n", stderr="")

    monkeypatch.setattr(gateway.subprocess, "run", fake_run)

    result = gateway.invoke_agent(
        "fix everything", workdir=str(tmp_path), client="codex", timeout_seconds=60
    )

    command = calls[0][0]
    assert result["success"] is True
    assert result["mode"] == "fast:fast"
    assert result["autonomy"] == "yolo"
    assert result["capabilities"] == ["file/search/patch"]
    assert "--yolo" in command
    assert command[command.index("--source") + 1] == "tool"
    assert "fast:fast" not in command  # profile, never an invalid model ID
    prompt = command[command.index("-q") + 1]
    assert "mode=fast:fast" in prompt
    assert "file/search/patch" in prompt


def test_invoke_agent_rejects_invalid_workdir(tmp_path):
    result = gateway.invoke_agent("act", workdir=str(tmp_path / "missing"))
    assert result["success"] is False
    assert "not an existing directory" in result["error"]


def test_rank_capabilities_fails_closed_without_request(tmp_path):
    result = gateway.rank_capabilities("  ", workdir=str(tmp_path))
    assert result == {
        "success": False,
        "error": "request is required",
        "mode": "fast:fast",
    }


def test_gateway_tools_are_registered(monkeypatch):
    import mcp_serve

    class FakeMCP:
        def __init__(self, *args, **kwargs):
            self.names = []

        def tool(self, *args, **kwargs):
            def decorator(fn):
                self.names.append(fn.__name__)
                return fn

            return decorator

    monkeypatch.setattr(mcp_serve, "FastMCP", FakeMCP)
    monkeypatch.setattr(mcp_serve, "_MCP_SERVER_AVAILABLE", True)
    server = mcp_serve.create_mcp_server(event_bridge=SimpleNamespace())

    assert "simplicio_capabilities" in server.names
    assert "simplicio_act" in server.names
