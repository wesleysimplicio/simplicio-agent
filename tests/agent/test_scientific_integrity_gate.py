"""Focused tests for issue #141's bounded scientific integrity gate."""

from __future__ import annotations

from copy import deepcopy

import pytest

from agent.scientific_integrity_gate import (
    CONTRACT_SCHEMA,
    INTEGRITY_SCOPE,
    ScientificIntegrityError,
    assert_valid_manifest,
    check_manifest,
    validate_manifest,
)


def _valid_manifest() -> dict[str, object]:
    return {
        "schema": CONTRACT_SCHEMA,
        "hypothesis": "The bounded adapter reduces replay failures.",
        "assumptions": ["The declared input domain is finite."],
        "falsifier": "A replay test fails under the declared domain.",
        "boundary": "Only the documented adapter and fixture domain are covered.",
        "license": "MIT",
        "source": {
            "url": "https://example.invalid/source",
            "commit": "0123456789abcdef0123456789abcdef01234567",
        },
        "benchmark_evidence": {
            "command": "python -m pytest tests/benchmark/test_adapter.py",
            "dataset": "fixtures/adapter-v1.json",
            "result": "12 passed",
            "reproducible": True,
        },
    }


def test_valid_manifest_is_accepted_without_claiming_scientific_truth() -> None:
    result = validate_manifest(_valid_manifest())

    assert result.accepted is True
    assert result.valid is True
    assert result.errors == ()
    assert "no ASOLARIA" in INTEGRITY_SCOPE
    assert check_manifest(_valid_manifest()) is True
    assert_valid_manifest(_valid_manifest()) == result


@pytest.mark.parametrize(
    "field",
    ("schema", "hypothesis", "assumptions", "falsifier", "boundary", "license"),
)
def test_missing_required_top_level_fields_fail_closed(field: str) -> None:
    manifest = _valid_manifest()
    manifest.pop(field)

    result = validate_manifest(manifest)

    assert result.accepted is False
    assert any(field in error for error in result.errors)


@pytest.mark.parametrize("nested", ("url", "commit"))
def test_missing_source_provenance_fails_closed(nested: str) -> None:
    manifest = _valid_manifest()
    source = manifest["source"]
    assert isinstance(source, dict)
    source.pop(nested)

    result = validate_manifest(manifest)

    assert result.accepted is False
    assert f"source.{nested}" in " ".join(result.errors)


@pytest.mark.parametrize(
    "change",
    (
        {"source": {"url": "https://example.invalid/source", "commit": "not-a-sha"}},
        {"source": {"url": "", "commit": "0123456789abcdef0123456789abcdef01234567"}},
        {"source": None},
    ),
)
def test_invalid_source_values_fail_closed(change: dict[str, object]) -> None:
    manifest = _valid_manifest()
    manifest.update(change)

    assert validate_manifest(manifest).accepted is False


@pytest.mark.parametrize(
    "nested",
    ("command", "dataset", "result", "reproducible"),
)
def test_benchmark_evidence_requires_reproducible_receipt(nested: str) -> None:
    manifest = _valid_manifest()
    evidence = manifest["benchmark_evidence"]
    assert isinstance(evidence, dict)
    if nested == "reproducible":
        evidence[nested] = False
    else:
        evidence.pop(nested)

    result = validate_manifest(manifest)

    assert result.accepted is False
    assert "benchmark_evidence" in " ".join(result.errors)


def test_malformed_input_and_raising_helper_fail_closed() -> None:
    assert validate_manifest(None).accepted is False
    assert check_manifest([]) is False

    invalid = deepcopy(_valid_manifest())
    invalid["hypothesis"] = ""
    with pytest.raises(ScientificIntegrityError, match="scientific integrity gate failed"):
        assert_valid_manifest(invalid)
