"""Tests for ``agent.toon_codec`` (TOON encode/decode).

Covers lossless round-trip for the shapes described in the TOON spec
(https://github.com/toon-format/toon) plus the mandatory fallback-to-JSON
behavior for arrays that aren't uniform.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent.toon_codec import (
    ToonDecodeError,
    from_toon,
    parse_tool_payload,
    to_toon,
    to_toon_or_json,
    to_toon_report,
)

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.toon_contract_runner import (  # noqa: E402
    _load_manifest as _load_toon_contract_manifest,
    check_invalid_case as _check_toon_contract_invalid_case,
    check_valid_case as _check_toon_contract_valid_case,
)


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
    pytest.param(
        {"items": [{"id": 1, "tags": [1, 2]}, {"id": 2, "tags": []}]},
        id="uniform-array-with-list-of-scalars-cells",
    ),
    pytest.param(
        {"items": [{"id": 1, "tags": [1]}]},
        id="one-element-list-cell-is-not-ambiguous-with-scalar",
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


def test_array_with_dict_valued_cell_falls_back():
    # A dict-valued cell (not a list of scalars) cannot take the tabular
    # path and must fall back to an embedded JSON blob (TOON-CONTRACT.md
    # §4, reason "nested_containers").
    value = {"items": [{"a": 1, "b": {"c": 1}}, {"a": 2, "b": {"c": 2}}]}
    encoded = to_toon(value)
    assert "items[2]{" not in encoded
    assert from_toon(encoded) == value


def test_array_with_list_of_scalar_cells_uses_tabular_path():
    # A cell whose value is a list of *scalars* DOES take the tabular path
    # -- the list-cell rule (TOON-CONTRACT.md §4, fixed upstream in
    # simplicio-mapper#148 after being found to cost most of the promised
    # compression: real shapes like files[].exports/imports are exactly
    # this).
    value = {"items": [{"a": 1, "b": [1, 2]}, {"a": 2, "b": [3, 4]}]}
    encoded = to_toon(value)
    lines = encoded.split("\n")
    assert lines[0] == "items[2]{a,b}:"
    assert lines[1] == "  1,[1,2]"
    assert lines[2] == "  2,[3,4]"
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


# ---------------------------------------------------------------------------
# Fallback report (TOON-CONTRACT.md §3, issue #16/#149)
# ---------------------------------------------------------------------------


def test_to_toon_report_matches_to_toon_for_the_encoded_text():
    value = {"items": [{"a": 1}, {"b": 2}]}
    encoded, _report = to_toon_report(value)
    assert encoded == to_toon(value)


def test_to_toon_report_records_differing_keys_fallback():
    _encoded, report = to_toon_report({"items": [{"a": 1}, {"b": 2}]})
    assert report == [{"path": "$.items", "reason": "differing_keys"}]


def test_to_toon_report_records_mixed_types_fallback():
    _encoded, report = to_toon_report({"a": [1, "x", {"z": 1}]})
    assert report == [{"path": "$.a", "reason": "mixed_types"}]


def test_to_toon_report_records_nested_containers_fallback_with_dotted_path():
    _encoded, report = to_toon_report({"deep": {"items": [{"a": 1, "b": {"c": 1}}]}})
    assert report == [{"path": "$.deep.items", "reason": "nested_containers"}]


def test_to_toon_report_empty_array_is_not_a_fallback():
    # An empty array has its own canonical encoding (`key: []`) -- it is
    # not a lossy fallback, so it must not appear in the report.
    _encoded, report = to_toon_report({"empty": []})
    assert report == []


def test_to_toon_report_list_cell_is_not_a_fallback():
    # The list-cell rule means a list-of-scalars cell takes the tabular
    # path -- it must not be reported as a fallback either.
    _encoded, report = to_toon_report({"items": [{"id": 1, "tags": [1, 2]}]})
    assert report == []


def test_to_toon_report_no_fallbacks_for_clean_payload():
    _encoded, report = to_toon_report({"a": 1, "users": [{"id": 1, "name": "Alice"}]})
    assert report == []


# ---------------------------------------------------------------------------
# Decode error hardening (TOON-CONTRACT.md §5, issue #16/#149)
# ---------------------------------------------------------------------------


def test_toon_decode_error_is_a_value_error():
    assert issubclass(ToonDecodeError, ValueError)


def test_from_toon_raises_on_truncated_root_table():
    with pytest.raises(ToonDecodeError, match="Truncated"):
        from_toon("[2]{file,lines}:\n  a.py,10")


def test_from_toon_raises_on_truncated_nested_table():
    with pytest.raises(ToonDecodeError, match="Truncated"):
        from_toon("files[2]{path,lines}:\n  a.py,10")


def test_from_toon_raises_on_row_field_count_mismatch():
    with pytest.raises(ToonDecodeError, match="mismatch"):
        from_toon("files[1]{path,lines}:\n  a.py,10,extra")


def test_from_toon_raises_on_malformed_array_header():
    with pytest.raises(ToonDecodeError, match="Malformed"):
        from_toon("[2{file,lines}:\n  a.py,10\n  b.py,20")


def test_from_toon_raises_on_unterminated_quote():
    with pytest.raises(ToonDecodeError, match="quoted"):
        from_toon('name: "unterminated')


def test_from_toon_raises_on_truncated_scalar_array():
    with pytest.raises(ToonDecodeError):
        from_toon("tags[3]: a,b")


# ---------------------------------------------------------------------------
# TOON-CONTRACT golden-corpus conformance (issue #16/#149)
#
# tests/fixtures/toon-golden/ + the root TOON-CONTRACT.md are vendored
# verbatim from the canonical host, simplicio-mapper (issue #149). See
# scripts/toon_contract_runner.py for what "conformance" means here (this
# repo's codec is not the reference implementation, so byte-identical
# encoding is not required -- only lossless round-trip and cross-repo
# decode interop).
# ---------------------------------------------------------------------------

_TOON_CONTRACT_MANIFEST = _load_toon_contract_manifest()


@pytest.mark.parametrize(
    "case_id",
    [case["id"] for case in _TOON_CONTRACT_MANIFEST["valid"]],
)
def test_toon_contract_valid_case_conforms(case_id):
    failures = _check_toon_contract_valid_case(case_id)
    assert failures == [], "\n".join(failures)


@pytest.mark.parametrize(
    "case_id",
    [case["id"] for case in _TOON_CONTRACT_MANIFEST["invalid"]],
)
def test_toon_contract_invalid_case_conforms(case_id):
    failures = _check_toon_contract_invalid_case(case_id)
    assert failures == [], "\n".join(failures)


def test_toon_contract_manifest_lists_at_least_one_case_of_each_kind():
    assert len(_TOON_CONTRACT_MANIFEST.get("valid", [])) > 0
    assert len(_TOON_CONTRACT_MANIFEST.get("invalid", [])) > 0
