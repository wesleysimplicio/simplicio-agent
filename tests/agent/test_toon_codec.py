"""Tests for ``agent.toon_codec`` (TOON encode/decode).

Covers lossless round-trip for the shapes described in the TOON spec
(https://github.com/toon-format/toon) plus the mandatory fallback-to-JSON
behavior for arrays that aren't uniform.
"""

from __future__ import annotations

import json

import pytest

from agent.toon_codec import from_toon, to_toon


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
