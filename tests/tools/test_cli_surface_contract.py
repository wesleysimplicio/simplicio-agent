"""Tests for the bounded CLI/TUI identity contract (issue #188)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.cli_surface_contract import (
    CANONICAL_COMMAND,
    CLI_SURFACE_CHECK_SCHEMA,
    CLI_SURFACE_RECEIPT_SCHEMA,
    CliSurfaceSchemaError,
    check_manifest,
    classify_public_message,
    default_manifest,
    load_manifest,
    validate_manifest,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "cli-identity"


def _load_raw(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_default_manifest_matches_bounded_identity_contract():
    manifest = default_manifest()

    report = check_manifest(manifest)

    assert report["schema"] == CLI_SURFACE_CHECK_SCHEMA
    assert report["ok"] is True
    assert report["canonical_command"] == CANONICAL_COMMAND
    assert report["legacy_alias_count"] == 3
    assert report["receipt_count"] == 1


def test_fixture_manifest_loads_and_validates():
    manifest = load_manifest(FIXTURES / "valid-manifest.json")

    validated = validate_manifest(manifest)

    assert validated.canonical_command == CANONICAL_COMMAND
    assert [entry.alias for entry in validated.legacy_aliases] == [
        "hermes",
        "hermes-agent",
        "hermes-acp",
    ]
    assert validated.receipts[0].payload["schema"] == CLI_SURFACE_RECEIPT_SCHEMA


@pytest.mark.parametrize(
    ("message_id", "surface", "text", "expected"),
    [
        (
            "cli.deprecated_alias_notice",
            "cli",
            "note: `hermes` is a deprecated alias; use `simplicio-agent` (same CLI, new name).",
            "migration_notice",
        ),
        ("gateway.ready", "tui", "gateway.ready publishes branding.agent_name=Simplicio Agent.", "branding_event"),
        ("cli.help.doctor", "cli", "Run `simplicio-agent doctor` for diagnostics.", "canonical_hint"),
        ("cli.neutral", "cli", "Diagnostics completed successfully.", "neutral_public_text"),
    ],
)
def test_public_message_classification_is_deterministic(message_id, surface, text, expected):
    assert classify_public_message(message_id=message_id, surface=surface, text=text) == expected


def test_bad_message_classification_is_rejected():
    manifest = load_manifest(FIXTURES / "invalid-message-classification.json")

    report = check_manifest(manifest)

    assert report["ok"] is False
    assert any("classification must be" in error for error in report["errors"])


def test_non_migration_message_may_not_emit_legacy_alias():
    manifest = load_manifest(FIXTURES / "invalid-legacy-message.json")

    report = check_manifest(manifest)

    assert report["ok"] is False
    assert any("mentions legacy alias outside migration_notice" in error for error in report["errors"])


def test_secret_bearing_receipt_is_rejected():
    manifest = load_manifest(FIXTURES / "invalid-secret-receipt.json")

    report = check_manifest(manifest)

    assert report["ok"] is False
    assert any("leaks sensitive fields" in error for error in report["errors"])


def test_validate_manifest_raises_for_invalid_schema(tmp_path):
    raw = _load_raw("valid-manifest.json")
    raw["canonical_command"] = "hermes"
    tmp = tmp_path / "invalid-manifest.json"
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(CliSurfaceSchemaError, match="canonical_command must be"):
        validate_manifest(load_manifest(tmp))
