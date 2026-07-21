from __future__ import annotations

import hashlib
import json

import pytest

from tools.runtime_lock_contract import (
    LOCK_SCHEMA,
    load_lock,
    target_key,
    validate_lock,
)


def _lock(tmp_path, *, signature="verified", target="linux-x86_64", payload=b"runtime"):
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "schema": LOCK_SCHEMA,
        "min_version": "3.5.0",
        "provenance": {"signature_status": signature},
        "assets": {
            target: {
                "name": "simplicio",
                "version": "3.5.0",
                "url": "https://example.invalid/releases/simplicio",
                "sha256": digest,
                "size": len(payload),
                "target": {"os": "linux", "arch": "x86_64"},
            }
        },
    }, payload


def test_valid_lock_and_verified_artifact_are_stable_ready(tmp_path):
    lock, payload = _lock(tmp_path)
    artifact = tmp_path / "simplicio"
    artifact.write_bytes(payload)
    receipt = validate_lock(lock, target="linux-x86_64", artifact=artifact)
    assert receipt.valid is True
    assert receipt.stable_ready is True
    assert receipt.errors == ()


def test_unverified_signature_is_not_stable_ready(tmp_path):
    lock, _ = _lock(tmp_path, signature="not-proven")
    receipt = validate_lock(lock, target="linux-x86_64")
    assert receipt.valid is True
    assert receipt.stable_ready is False


def test_asset_below_minimum_version_fails_closed(tmp_path):
    lock, _ = _lock(tmp_path)
    lock["min_version"] = "3.6.0"
    receipt = validate_lock(lock, target="linux-x86_64")
    assert receipt.valid is False
    assert "asset.version must be >= min_version" in receipt.errors


def test_asset_version_must_match_explicit_url_release_tag(tmp_path):
    lock, _ = _lock(tmp_path)
    lock["assets"]["linux-x86_64"]["url"] = (
        "https://example.invalid/releases/download/v3.6.0/simplicio"
    )
    receipt = validate_lock(lock, target="linux-x86_64")
    assert receipt.valid is False
    assert "asset.version does not match URL release tag" in receipt.errors


@pytest.mark.parametrize("field", ["sha256", "size", "url", "version"])
def test_missing_pinned_metadata_fails_closed(tmp_path, field):
    lock, _ = _lock(tmp_path)
    lock["assets"]["linux-x86_64"][field] = None
    receipt = validate_lock(lock, target="linux-x86_64")
    assert receipt.valid is False
    assert receipt.errors


def test_wrong_target_and_tampered_bytes_fail(tmp_path):
    lock, payload = _lock(tmp_path)
    artifact = tmp_path / "simplicio"
    artifact.write_bytes(payload + b"tamper")
    wrong = validate_lock(lock, target="darwin-arm64", artifact=artifact)
    tampered = validate_lock(lock, target="linux-x86_64", artifact=artifact)
    assert wrong.valid is False and "no asset" in wrong.errors[0]
    assert tampered.valid is False
    assert "sha256" in " ".join(tampered.errors)


def test_load_lock_does_not_apply_defaults(tmp_path):
    path = tmp_path / "runtime.lock"
    path.write_text(json.dumps({"schema": LOCK_SCHEMA}), encoding="utf-8")
    assert load_lock(path) == {"schema": LOCK_SCHEMA}


def test_target_aliases_are_normalized():
    assert target_key("Linux", "amd64") == "linux-x86_64"
    assert target_key("Darwin", "aarch64") == "darwin-arm64"
