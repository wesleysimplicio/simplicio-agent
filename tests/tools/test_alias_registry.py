"""Tests for the bounded alias registry slice (issue #193)."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from tools.alias_registry import (
    ALIAS_RECEIPT_SCHEMA,
    ALIAS_WARNING_SCHEMA,
    AliasCollisionError,
    AliasSchemaError,
    load_alias_document,
    load_alias_registry,
    normalize_alias,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "aliases"


def test_normalize_alias_is_casefolded_and_trimmed():
    assert normalize_alias("  Hermes-Agent  ") == "hermes-agent"


def test_load_valid_registry_exposes_canonical_legacy_mapping():
    registry = load_alias_registry(FIXTURES / "valid")

    assert registry.legacy_map == {
        "hermes": "simplicio-agent",
        "hermes-agent": "simplicio-agent",
        "hermes-acp": "simplicio-agent",
    }


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
