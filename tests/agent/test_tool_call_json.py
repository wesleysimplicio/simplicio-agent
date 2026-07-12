"""Behavioral tests for the tool-call JSON hot path."""

from __future__ import annotations

import json

import pytest

import agent.tool_call_json as tool_call_json
from agent.tool_call_json import (
    dumps_tool_call_arguments,
    loads_tool_call_arguments,
    parse_tool_call_arguments,
)


@pytest.mark.parametrize(
    "raw",
    [
        '{"query":"ação 🚀","limit":3,"nested":{"ok":true}}',
        '{"text":"\u00e9\ud83d\ude80","values":[1,null,false]}',
    ],
)
def test_loads_tool_call_arguments_matches_stdlib_for_unicode_and_arguments(raw: str) -> None:
    assert loads_tool_call_arguments(raw) == json.loads(raw)
    assert parse_tool_call_arguments(raw) == json.loads(raw)


def test_loads_tool_call_arguments_preserves_stdlib_error_for_invalid_json() -> None:
    raw = '{"query": "unterminated}'

    with pytest.raises(json.JSONDecodeError):
        loads_tool_call_arguments(raw)

    with pytest.raises(json.JSONDecodeError):
        parse_tool_call_arguments(raw)


def test_loads_tool_call_arguments_falls_back_when_fast_backend_rejects_input(monkeypatch) -> None:
    raw = '{"text":"\\ud800"}'

    def reject(_raw):
        raise ValueError("optional backend rejected input")

    monkeypatch.setattr(tool_call_json, "_fast_loads", reject)

    assert loads_tool_call_arguments(raw) == json.loads(raw)


def test_parse_tool_call_arguments_keeps_only_object_arguments() -> None:
    assert parse_tool_call_arguments('{"answer":42}') == {"answer": 42}
    assert parse_tool_call_arguments('[1, 2, 3]') == {}


def test_dumps_tool_call_arguments_roundtrips_unicode_and_nested_arguments() -> None:
    arguments = {"query": "ação 🚀", "options": {"limit": 3, "dry_run": True}}

    encoded = dumps_tool_call_arguments(arguments)

    assert isinstance(encoded, str)
    assert json.loads(encoded) == arguments
    assert "\\u00e7" not in encoded


def test_dumps_tool_call_arguments_supports_stable_tool_call_serialization() -> None:
    arguments = {"z": 1, "name": "工具", "a": [True, None]}

    encoded = dumps_tool_call_arguments(arguments, sort_keys=True)

    assert encoded == '{"a":[true,null],"name":"工具","z":1}'


def test_tool_call_envelope_roundtrips_through_argument_helpers() -> None:
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "search",
            "arguments": dumps_tool_call_arguments({"query": "ação 🚀"}),
        },
    }

    assert parse_tool_call_arguments(tool_call["function"]["arguments"]) == {
        "query": "ação 🚀"
    }
