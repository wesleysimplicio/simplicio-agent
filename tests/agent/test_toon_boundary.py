"""Tests for the TOON tool_executor chokepoint (issue #16).

``maybe_toon_encode_tool_result`` is a pure gating function: off unless the
session-pinned flag is set, exempt tools pass through, non-JSON results
pass through, and a successful conversion is lossless and telemetered.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.toon_boundary import TOON_EXEMPT_TOOLS, maybe_toon_encode_tool_result
from agent.toon_codec import from_toon


@pytest.fixture(autouse=True)
def _isolated_savings_log(tmp_path, monkeypatch):
    """Every test in this file writes telemetry (if any) to a tmp file,
    never to the real ~/.hermes/telemetry/token_savings.jsonl."""
    monkeypatch.setenv("HERMES_TOKEN_SAVINGS_LOG", str(tmp_path / "token_savings.jsonl"))


def _agent(**overrides):
    defaults = dict(
        _toon_prompts_enabled=True,
        model="gpt-5",
        provider="openai",
        session_id="sess-1",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_noop_when_flag_off():
    agent = _agent(_toon_prompts_enabled=False)
    raw = json.dumps({"a": 1})
    assert maybe_toon_encode_tool_result(agent, "read_file", raw) == raw


def test_noop_when_flag_missing_entirely():
    # An agent instance predating this feature (or a code path that
    # bypasses agent_init) has no _toon_prompts_enabled attribute at all --
    # must default to off, never raise.
    agent = SimpleNamespace(model="x", provider="y", session_id="z")
    raw = json.dumps({"a": 1})
    assert maybe_toon_encode_tool_result(agent, "read_file", raw) == raw


def test_converts_json_dict_result_when_enabled():
    agent = _agent()
    raw = json.dumps({"success": True, "files_modified": ["a.py", "b.py"]})
    out = maybe_toon_encode_tool_result(agent, "write_file", raw)
    assert out != raw
    assert from_toon(out) == {"success": True, "files_modified": ["a.py", "b.py"]}


def test_converts_json_list_result_when_enabled():
    agent = _agent()
    raw = json.dumps([{"id": 1, "n": "a"}, {"id": 2, "n": "b"}])
    out = maybe_toon_encode_tool_result(agent, "search", raw)
    assert from_toon(out) == [{"id": 1, "n": "a"}, {"id": 2, "n": "b"}]


def test_exempt_tool_passes_through_unchanged():
    agent = _agent()
    raw = json.dumps({"items": [{"id": 1}]})
    assert "todo_write" in TOON_EXEMPT_TOOLS
    assert maybe_toon_encode_tool_result(agent, "todo_write", raw) == raw


def test_config_extended_exempt_tool_passes_through_unchanged():
    agent = _agent(_toon_exempt_tools=["my_custom_tool"])
    raw = json.dumps({"a": 1})
    assert maybe_toon_encode_tool_result(agent, "my_custom_tool", raw) == raw


def test_non_string_result_passes_through_unchanged():
    agent = _agent()
    multimodal = [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {}}]
    assert maybe_toon_encode_tool_result(agent, "screenshot", multimodal) is multimodal


def test_plain_text_result_passes_through_unchanged():
    agent = _agent()
    text = "Error executing tool 'x': network timeout"
    assert maybe_toon_encode_tool_result(agent, "read_file", text) == text


def test_persisted_output_block_passes_through_unchanged():
    agent = _agent()
    text = "<persisted-output>\nThis tool result was too large...\n</persisted-output>"
    assert maybe_toon_encode_tool_result(agent, "read_file", text) == text


def test_malformed_json_passes_through_unchanged():
    agent = _agent()
    text = "{not actually valid json"
    assert maybe_toon_encode_tool_result(agent, "read_file", text) == text


def test_records_savings_to_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_TOKEN_SAVINGS_LOG", str(tmp_path / "savings.jsonl"))
    agent = _agent()
    raw = json.dumps({"users": [{"id": i, "name": f"u{i}"} for i in range(10)]})
    maybe_toon_encode_tool_result(agent, "list_users", raw, session_id="sess-42")

    from agent.telemetry.token_savings import iter_records
    records = list(iter_records(tmp_path / "savings.jsonl"))
    assert len(records) == 1
    rec = records[0]
    assert rec["tool"] == "list_users"
    assert rec["session"] == "sess-42"
    assert rec["raw_tokens"] >= rec["compressed_tokens"]


def test_telemetry_failure_does_not_break_conversion(monkeypatch):
    """A broken ledger writer must never take down tool execution.

    Patches the real dependency *inside* _record_savings' try/except
    (record_token_saving itself) rather than replacing _record_savings —
    this exercises the actual safety net, not a stand-in for it.
    """
    agent = _agent()
    raw = json.dumps({"a": 1})

    from agent.telemetry import token_savings as ts_module

    def _boom(*a, **k):
        raise RuntimeError("ledger write boom")

    monkeypatch.setattr(ts_module, "record_token_saving", _boom)

    out = maybe_toon_encode_tool_result(agent, "x", raw)
    assert from_toon(out) == {"a": 1}
