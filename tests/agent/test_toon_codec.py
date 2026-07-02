"""Tests for ``agent.toon_codec`` (TOON encode/decode).

Covers lossless round-trip for the shapes described in the TOON spec
(https://github.com/toon-format/toon) plus the mandatory fallback-to-JSON
behavior for arrays that aren't uniform.
"""

from __future__ import annotations

import json

import pytest

from agent.toon_codec import from_toon, parse_tool_payload, to_toon, to_toon_or_json


# ---------------------------------------------------------------------------
# Round-trip fixtures
# ---------------------------------------------------------------------------

ROUNDTRIP_CASES = [
    pytest.param({"a": 1, "b": "x", "c": [1, 2, 3]}, id="flat-dict-scalar-array"),
    pytest.param(
        {
            "users": [
                {"id": 1, "name": "Alice", "active": True},
                {"id": 2, "name": "Bob", "active": False},
            ]
        },
        id="uniform-array-of-objects",
    ),
    pytest.param({"nested": {"a": {"b": {"c": 1}}}}, id="nested-objects"),
    pytest.param({"empty_arr": [], "empty_obj": {}}, id="empty-array-and-object"),
    pytest.param([1, 2, 3], id="root-scalar-array"),
    pytest.param(
        [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        id="root-uniform-array-of-objects",
    ),
    pytest.param({}, id="root-empty-object"),
    pytest.param([], id="root-empty-array"),
    pytest.param("hello world", id="root-scalar-string"),
    pytest.param(5, id="root-scalar-int"),
    pytest.param(5.5, id="root-scalar-float"),
    pytest.param(True, id="root-scalar-bool"),
    pytest.param(None, id="root-scalar-none"),
    pytest.param(
        {
            "s": "has, comma",
            "t": "has:colon",
            "u": " leading space",
            "v": "trailing space ",
            "w": "",
            "x": "true",
            "y": "42",
            "z": "null",
        },
        id="strings-requiring-quotes",
    ),
    pytest.param({"quote": 'she said "hi"'}, id="string-with-embedded-quotes"),
    pytest.param({"newline": "line1\nline2"}, id="string-with-newline"),
    pytest.param(
        {"deep": [{"a": {"b": 1}, "c": 2}, {"a": {"b": 2}, "c": 3}]},
        id="array-of-objects-with-nested-non-scalar-values-falls-back",
    ),
    pytest.param(
        {"mixed": [1, {"a": 1}, "x", None, True]},
        id="mixed-type-array-falls-back",
    ),
    pytest.param(
        {"differing_keys": [{"a": 1}, {"b": 2}]},
        id="differing-key-arrays-fall-back",
    ),
    pytest.param([{}], id="array-of-empty-dicts"),
    pytest.param(
        {"a": [1, "two", 3.5, None, True, False]},
        id="scalar-array-mixed-scalar-types",
    ),
    pytest.param(
        {"big": {"list": [{"id": i, "even": i % 2 == 0} for i in range(25)]}},
        id="larger-uniform-array",
    ),
]


@pytest.mark.parametrize("value", ROUNDTRIP_CASES)
def test_roundtrip(value):
    encoded = to_toon(value)
    assert isinstance(encoded, str)
    assert from_toon(encoded) == value


def test_roundtrip_double_pass_is_stable():
    value = {
        "items": [{"id": 1, "tags": ["a", "b"]}, {"id": 2, "tags": ["c"]}],
        "meta": {"count": 2, "ok": True},
    }
    once = to_toon(from_toon(to_toon(value)))
    twice = to_toon(from_toon(once))
    assert once == twice


# ---------------------------------------------------------------------------
# Non-uniform array fallback behavior
# ---------------------------------------------------------------------------


def test_non_uniform_array_falls_back_to_compact_json():
    value = {"items": [{"a": 1}, {"b": 2}]}
    encoded = to_toon(value)
    # No tabular header (no "{" field list) should be emitted for this key.
    assert "items[2]{" not in encoded
    assert "items: " in encoded
    fallback_blob = encoded.split("items: ", 1)[1]
    assert json.loads(fallback_blob) == value["items"]


def test_empty_array_falls_back_to_compact_json():
    value = {"tags": []}
    encoded = to_toon(value)
    assert encoded == "tags: []"


def test_mixed_type_array_falls_back_to_compact_json():
    value = {"mixed": [1, "two", {"a": 3}]}
    encoded = to_toon(value)
    assert "mixed: " in encoded
    blob = encoded.split("mixed: ", 1)[1]
    assert json.loads(blob) == value["mixed"]


def test_array_with_nested_containers_falls_back():
    value = {"items": [{"a": 1, "b": [1, 2]}, {"a": 2, "b": [3, 4]}]}
    encoded = to_toon(value)
    assert "items[2]{" not in encoded
    assert from_toon(encoded) == value


# ---------------------------------------------------------------------------
# Tabular shape assertions (uniform arrays actually compress)
# ---------------------------------------------------------------------------


def test_uniform_array_uses_tabular_header():
    value = {
        "users": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
    }
    encoded = to_toon(value)
    lines = encoded.split("\n")
    assert lines[0] == "users[2]{id,name}:"
    assert lines[1] == "  1,Alice"
    assert lines[2] == "  2,Bob"


def test_scalar_array_uses_inline_list():
    value = {"tags": ["a", "b", "c"]}
    encoded = to_toon(value)
    assert encoded == "tags[3]: a,b,c"


def test_toon_is_shorter_than_json_for_uniform_arrays():
    value = {
        "users": [
            {"id": i, "name": f"user{i}", "active": i % 2 == 0} for i in range(20)
        ]
    }
    toon_len = len(to_toon(value))
    json_len = len(json.dumps(value))
    assert toon_len < json_len


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_from_toon_empty_string_returns_empty_object():
    assert from_toon("") == {}


def test_to_toon_root_empty_object_and_array():
    assert to_toon({}) == "{}"
    assert to_toon([]) == "[]"
    assert from_toon("{}") == {}
    assert from_toon("[]") == []


# ---------------------------------------------------------------------------
# to_toon_or_json / parse_tool_payload (issue #16 — shared boundary helpers)
# ---------------------------------------------------------------------------


def test_to_toon_or_json_matches_to_toon_for_normal_values():
    value = {"a": 1, "items": [{"id": 1, "n": "x"}, {"id": 2, "n": "y"}]}
    assert to_toon_or_json(value) == to_toon(value)


def test_to_toon_or_json_falls_back_to_compact_json_when_to_toon_raises(monkeypatch):
    import agent.toon_codec as toon_codec

    def _boom(_value):
        raise RuntimeError("simulated encoder failure")

    monkeypatch.setattr(toon_codec, "to_toon", _boom)
    out = toon_codec.to_toon_or_json({"a": 1})
    assert json.loads(out) == {"a": 1}


def test_parse_tool_payload_parses_json():
    assert parse_tool_payload('{"a": 1}') == {"a": 1}


def test_parse_tool_payload_parses_toon():
    encoded = to_toon({"success": True, "bytes_written": 12})
    assert parse_tool_payload(encoded) == {"success": True, "bytes_written": 12}


def test_parse_tool_payload_never_raises():
    for text in ("not json, not toon: {[}[", "plain prose with no colon", "", "   "):
        parse_tool_payload(text)  # must not raise, whatever it returns


def test_parse_tool_payload_single_colon_sentence_is_a_known_toon_grammar_edge():
    # A sentence with exactly one colon (e.g. "Error: timeout") matches
    # TOON's key-line grammar and decodes into {"Error": "timeout"} rather
    # than staying a plain string. This is a documented, accepted edge, not
    # a silent footgun: every caller in this codebase (file_mutation_result_
    # landed, background_review's action summarizer) gates on a SPECIFIC
    # required key ("success", "bytes_written") in addition to
    # isinstance(data, dict), so a spurious {"Error": "..."} dict still
    # evaluates to "not landed" / "not a notify-worthy action" downstream.
    # agent.agent_runtime_helpers.convert_to_trajectory_format avoids this
    # entirely by gating its from_toon attempt on the session's
    # context.toon_prompts flag instead of calling parse_tool_payload
    # unconditionally on arbitrary tool text.
    result = parse_tool_payload("Error: timeout")
    assert result == {"Error": "timeout"}


def test_parse_tool_payload_none_for_non_string_input():
    assert parse_tool_payload(None) is None
    assert parse_tool_payload(42) is None
    assert parse_tool_payload("") is None
    assert parse_tool_payload("   ") is None
