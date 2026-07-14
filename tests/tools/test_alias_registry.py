"""Tests for the bounded alias registry slice (issue #193)."""

from __future__ import annotations

import json
import shutil
import tomllib
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tools.alias_registry import (
    ALIAS_RECEIPT_SCHEMA,
    ALIAS_WARNING_SCHEMA,
    AliasCollisionError,
    AliasContractError,
    AliasRegistry,
    AliasSchemaError,
    CLI_ALIAS_CANONICAL,
    CLI_ALIAS_NAMES,
    CLI_ALIAS_OWNER,
    CLI_ALIAS_WARNING_CODE,
    default_cli_alias_entries,
    load_alias_document,
    load_alias_registry,
    normalize_alias,
    validate_alias_contract,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "aliases"
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _project_entrypoints() -> dict[str, str]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]


def test_default_cli_alias_entries_are_versioned_compatibility_metadata():
    entries = default_cli_alias_entries()

    assert tuple(entry.alias for entry in entries) == CLI_ALIAS_NAMES
    assert {entry.alias: entry.canonical for entry in entries} == {
        "hermes": CLI_ALIAS_CANONICAL,
        "hermes-agent": CLI_ALIAS_CANONICAL,
        "hermes-acp": "simplicio-agent-acp",
    }
    assert {entry.owner for entry in entries} == {CLI_ALIAS_OWNER}
    assert {entry.warning_code for entry in entries} == {CLI_ALIAS_WARNING_CODE}
    assert {entry.deprecated_since for entry in entries} == {"2026-07-13"}
    assert {entry.warning_cadence for entry in entries} == {"once_per_process"}
    assert {entry.remove_after for entry in entries} == {"2027-01-01"}
    assert {entry.minimum_release_window for entry in entries} == {2}
    assert all(entry.deprecated and entry.note == "migration_only" for entry in entries)


def test_normalize_alias_is_casefolded_and_trimmed():
    assert normalize_alias("  Hermes-Agent  ") == "hermes-agent"


def test_load_valid_registry_exposes_canonical_legacy_mapping():
    registry = load_alias_registry(FIXTURES / "valid")

    assert registry.legacy_map == {
        "hermes": "simplicio-agent",
        "hermes-agent": "simplicio-agent",
        "hermes-acp": "simplicio-agent-acp",
    }


def test_repository_alias_contract_has_window_and_no_alias_specific_logic():
    registry = load_alias_registry(FIXTURES / "valid")

    validated = validate_alias_contract(registry, _project_entrypoints())

    assert validated is registry
    assert registry.lookup(["hermes-acp"]).canonical == "simplicio-agent-acp"


def test_builtin_alias_contract_matches_real_entrypoints():
    registry = AliasRegistry(default_cli_alias_entries())

    assert validate_alias_contract(registry, _project_entrypoints()) is registry


def test_alias_contract_rejects_window_shorter_than_two_releases():
    entries = list(default_cli_alias_entries())
    entries[0] = replace(entries[0], minimum_release_window=1)

    with pytest.raises(AliasContractError, match="must be between 2 and 3"):
        validate_alias_contract(AliasRegistry(entries), _project_entrypoints())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"deprecated_since": ""}, "requires deprecated_since"),
        ({"warning_cadence": "daily"}, "warning_cadence must be one of"),
        (
            {"remove_after": "2026-07-13"},
            "remove_after must follow deprecated_since",
        ),
    ],
)
def test_alias_contract_rejects_incomplete_deprecation_policy(changes, message):
    entries = list(default_cli_alias_entries())
    entries[0] = replace(entries[0], **changes)

    with pytest.raises(AliasContractError, match=message):
        validate_alias_contract(AliasRegistry(entries), _project_entrypoints())


def test_alias_contract_rejects_alias_specific_entrypoint_logic():
    entrypoints = _project_entrypoints()
    entrypoints["hermes"] = "compatibility.hermes:main"

    with pytest.raises(AliasContractError, match="alias-specific logic is forbidden"):
        validate_alias_contract(
            AliasRegistry(default_cli_alias_entries()), entrypoints
        )


def test_lookup_is_deterministic_and_warns_without_args_or_secrets():
    registry = load_alias_registry(FIXTURES / "valid")

    first = registry.lookup(
        ["hermes", "--api-key", "super-secret", "--token", "also-secret"],
        today=date(2026, 7, 13),
    )
    second = registry.lookup(
        ["HeRmEs", "--api-key", "different-secret"],
        today=date(2026, 7, 13),
    )

    assert first.canonical == "simplicio-agent"
    assert second.canonical == "simplicio-agent"
    assert first.warning is not None
    assert first.warning.schema == ALIAS_WARNING_SCHEMA
    assert first.warning.owner == "cli"
    assert first.warning.removal_state == "scheduled"
    assert first.receipt.schema == ALIAS_RECEIPT_SCHEMA
    assert first.receipt.argv_count == 5
    assert first.receipt.args_redacted is True
    receipt_blob = first.receipt.to_dict()
    assert "super-secret" not in str(receipt_blob)
    assert "also-secret" not in str(receipt_blob)
    assert second.warning is not None
    assert second.warning.to_dict() == first.warning.to_dict()


def test_unknown_lookup_receipt_redacts_all_arguments():
    registry = load_alias_registry(FIXTURES / "valid")

    lookup = registry.lookup([
        "not-a-command",
        "--password",
        "secret-value",
        "--token=token-value",
    ])

    assert lookup.warning is None
    assert lookup.receipt.argv_count == 4
    receipt_blob = str(lookup.receipt.to_dict())
    assert "secret-value" not in receipt_blob
    assert "token-value" not in receipt_blob


def test_entries_are_sorted_by_normalized_alias_for_deterministic_iteration():
    registry = load_alias_registry(FIXTURES / "valid")

    assert tuple(entry.alias for entry in registry.entries) == (
        "hermes",
        "hermes-acp",
        "hermes-agent",
        "simplicio-agent",
        "simplicio-agent-acp",
    )


def test_owner_deprecation_policy_flips_to_due_on_or_after_remove_after():
    registry = load_alias_registry(FIXTURES / "valid")

    scheduled = registry.lookup(["hermes-agent"], today=date(2026, 12, 31))
    due = registry.lookup(["hermes-agent"], today=date(2027, 1, 1))

    assert scheduled.warning is not None
    assert scheduled.warning.removal_state == "scheduled"
    assert due.warning is not None
    assert due.warning.removal_state == "due"
    assert due.receipt.removal_state == "due"


def test_unknown_alias_roundtrips_without_fake_warning():
    registry = load_alias_registry(FIXTURES / "valid")

    lookup = registry.lookup(["simplicio-agent"])

    assert lookup.canonical == "simplicio-agent"
    assert lookup.warning is None
    assert lookup.receipt.warning_code == ""


def test_collision_fixture_fails_load_with_clear_error():
    with pytest.raises(AliasCollisionError, match="alias collision for 'hermes'"):
        load_alias_registry(FIXTURES / "collision")


def test_invalid_document_version_is_rejected(tmp_path):
    shutil.copytree(FIXTURES / "valid", tmp_path / "valid")
    target = tmp_path / "valid" / "registry.json"
    target.write_text(
        target.read_text(encoding="utf-8").replace('"version": 1', '"version": 2'),
        encoding="utf-8",
    )

    with pytest.raises(AliasSchemaError, match="expected version 1"):
        load_alias_document(target)


def test_invalid_document_shape_fails_closed(tmp_path):
    root = tmp_path / "aliases"
    root.mkdir()
    target = root / "registry.json"
    target.write_text(
        '{"schema": "simplicio-agent/alias-registry/v1", "version": 1, '
        '"aliases": [null]}',
        encoding="utf-8",
    )

    with pytest.raises(AliasSchemaError, match=r"aliases\[0\] must be a JSON object"):
        load_alias_document(target)


def test_document_root_must_be_a_json_object(tmp_path):
    target = tmp_path / "registry.json"
    target.write_text("[]", encoding="utf-8")

    with pytest.raises(AliasSchemaError, match="document root must be a JSON object"):
        load_alias_document(target)


def test_invalid_fixture_is_rejected_instead_of_skipped():
    with pytest.raises(AliasSchemaError, match=r"aliases\[0\] must be a JSON object"):
        load_alias_registry(FIXTURES / "invalid")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alias", 123),
        ("canonical", False),
        ("deprecated", "true"),
        ("deprecated_since", 20260713),
        ("warning_cadence", 1),
        ("minimum_release_window", "2"),
    ],
)
def test_invalid_entry_types_are_rejected(tmp_path, field, value):
    root = tmp_path / "aliases"
    root.mkdir()
    target = root / "registry.json"
    entry = {"alias": "legacy", "canonical": "simplicio-agent"}
    entry[field] = value
    target.write_text(
        json.dumps({
            "schema": "simplicio-agent/alias-registry/v1",
            "version": 1,
            "aliases": [entry],
        }),
        encoding="utf-8",
    )

    with pytest.raises(AliasSchemaError, match=field):
        load_alias_document(target)
