"""Focused tests for the deterministic watcher gate."""

from tools.watcher_gate import (
    Verdict,
    compare_reported_to_recomputed,
    has_explicit_consent,
)


def test_verdicts_are_typed_and_have_stable_wire_values():
    assert Verdict.MEASURED.value == "MEASURED"
    assert isinstance(Verdict.CANON, str)
    assert {item.value for item in Verdict} == {
        "MEASURED",
        "CANON",
        "UNVERIFIED",
        "FABRICATED",
    }


def test_reported_and_recomputed_mapping_order_is_irrelevant():
    result = compare_reported_to_recomputed(
        {"b": 2, "a": [1, 3]},
        {"a": [1, 3], "b": 2},
    )

    assert result.verdict is Verdict.MEASURED
    assert result.matches is True
    assert result.passed is True


def test_mismatch_is_fabricated():
    result = compare_reported_to_recomputed({"count": 4}, {"count": 5})

    assert result.verdict is Verdict.FABRICATED
    assert result.matches is False
    assert result.passed is False


def test_canonical_source_gets_canon_verdict():
    result = compare_reported_to_recomputed("ok", "ok", source="canonical")

    assert result.verdict is Verdict.CANON
    assert result.status == "CANON"


def test_external_network_and_llm_sources_are_unverified_even_when_equal():
    for source in ("external", "network_api", "llm", "remote_model"):
        result = compare_reported_to_recomputed(1, 1, source=source)
        assert result.verdict is Verdict.UNVERIFIED
        assert result.matches is True
        assert result.passed is False


def test_consent_check_is_direct_and_non_recursive():
    assert has_explicit_consent(True) is True
    assert has_explicit_consent(False) is False
    assert has_explicit_consent({"consent": True}) is False
    assert has_explicit_consent([True]) is False
    assert has_explicit_consent("true") is False


def test_required_consent_blocks_before_comparison():
    result = compare_reported_to_recomputed(
        {"ok": True}, {"ok": True}, consent={"consent": True}, require_consent=True
    )

    assert result.verdict is Verdict.UNVERIFIED
    assert result.consented is False
    assert result.reported_canonical is None


def test_non_json_values_are_unverified():
    result = compare_reported_to_recomputed({"value": {1, 2}}, {"value": {1, 2}})

    assert result.verdict is Verdict.UNVERIFIED
    assert result.passed is False
