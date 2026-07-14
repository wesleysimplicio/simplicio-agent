"""Focused tests for issue #125's bounded Asolaria import gate."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from agent.asolaria_pattern_contract import (
    CONTRACT_SCHEMA,
    IMPORT_BOUNDARY,
    AsolariaPatternContractError,
    PatternImportManifest,
    PatternName,
    assert_valid_manifest,
    check_manifest,
    validate_manifest,
)


def _valid_manifest(pattern: str = "N-Nest") -> dict[str, object]:
    return {
        "schema": CONTRACT_SCHEMA,
        "issue_number": 125,
        "identity": {
            "name": pattern,
            "version": "v1",
            "summary": "deterministic corrective verification pattern",
        },
        "source": {
            "pattern": pattern,
            "repository": "JesseBrown1980/N-Nest-Prime",
            "url": "https://github.com/JesseBrown1980/N-Nest-Prime",
            "path": "README.md",
            "revision": "0123456789abcdef0123456789abcdef01234567",
            "evidence": ("public source specification reviewed",),
        },
        "hypothesis": "Independent recomputation catches a planted report fault.",
        "falsifier": "A tamper case passes the corrective gate undetected.",
        "license": {
            "source_license": "NO LICENSE",
            "import_mode": "reimplementation",
            "attribution": "Reimplemented from the public specification; no source bytes copied.",
        },
        "boundary": "Metadata contract only; it does not integrate simplicio-runtime.",
        "scientific_evidence": (
            "N-Nest depth cases catch tampering at every tested level.",
            "PRISM-COMB forward/inverse round trips close on the fixture set.",
        ),
        "benchmark": {
            "command": "python -m pytest skills/asolaria-patterns/tests -q",
            "dataset": "deterministic N-Nest and PRISM-COMB fixtures",
            "expected": "all cases pass",
            "observed": "all cases pass",
            "receipt": "local focused pytest receipt",
            "passed": True,
            "reproducible": True,
        },
    }


def test_valid_n_nest_manifest_is_accepted_and_round_trips() -> None:
    manifest = _valid_manifest()

    result = validate_manifest(manifest)
    typed = PatternImportManifest.from_mapping(manifest)

    assert result.accepted is True
    assert result.errors == ()
    assert typed.identity.name is PatternName.N_NEST
    assert typed.source.pattern is PatternName.N_NEST
    assert json.loads(typed.to_json()) == typed.to_dict()
    assert assert_valid_manifest(manifest) == result
    assert check_manifest(manifest) is True


def test_prism_comb_identity_and_provenance_are_supported() -> None:
    manifest = _valid_manifest("PRISM-COMB")

    typed = PatternImportManifest.from_mapping(manifest)

    assert typed.identity.name is PatternName.PRISM_COMB
    assert typed.source.pattern is PatternName.PRISM_COMB


@pytest.mark.parametrize(
    "field",
    (
        "identity",
        "source",
        "hypothesis",
        "falsifier",
        "license",
        "boundary",
        "scientific_evidence",
        "benchmark",
    ),
)
def test_missing_scientific_contract_fields_fail_closed(field: str) -> None:
    manifest = _valid_manifest()
    manifest.pop(field)

    result = validate_manifest(manifest)

    assert result.accepted is False
    assert any(field in error for error in result.errors)
    assert check_manifest(manifest) is False


def test_missing_benchmark_receipt_or_false_gate_fails_closed() -> None:
    missing_receipt = deepcopy(_valid_manifest())
    benchmark = missing_receipt["benchmark"]
    assert isinstance(benchmark, dict)
    benchmark.pop("receipt")
    assert validate_manifest(missing_receipt).accepted is False

    failed = deepcopy(_valid_manifest())
    failed_benchmark = failed["benchmark"]
    assert isinstance(failed_benchmark, dict)
    failed_benchmark["passed"] = False
    assert validate_manifest(failed).accepted is False


def test_source_revision_pattern_match_and_license_policy_are_checked() -> None:
    invalid_source = deepcopy(_valid_manifest())
    source = invalid_source["source"]
    assert isinstance(source, dict)
    source["pattern"] = "PRISM-COMB"
    source["revision"] = "not-a-revision"
    result = validate_manifest(invalid_source)
    assert result.accepted is False
    assert "source.pattern" in " ".join(result.errors)
    assert "source.revision" in " ".join(result.errors)

    copied_unlicensed = deepcopy(_valid_manifest())
    license_data = copied_unlicensed["license"]
    assert isinstance(license_data, dict)
    license_data["import_mode"] = "permissive"
    assert validate_manifest(copied_unlicensed).accepted is False


def test_malformed_input_raises_only_through_require_helper() -> None:
    assert validate_manifest(None).accepted is False
    assert validate_manifest([]).accepted is False

    invalid = _valid_manifest()
    invalid["scientific_evidence"] = []
    with pytest.raises(AsolariaPatternContractError, match="import gate failed"):
        assert_valid_manifest(invalid)


def test_boundary_is_explicit_and_no_runtime_module_is_loaded() -> None:
    result = validate_manifest(_valid_manifest())

    assert "metadata gate only" in IMPORT_BOUNDARY
    assert "simplicio-runtime integration" in result.scope
