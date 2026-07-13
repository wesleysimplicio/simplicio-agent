"""Focused local tests for the issue #129 staged-update contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli.update_contract import (
    ManifestError,
    UpdateContract,
    UpdateError,
    UpdateInterrupted,
    UpdateManifest,
    directory_sha256,
)


def _artifact(tmp_path: Path, version: str) -> tuple[Path, UpdateManifest]:
    artifact = tmp_path / f"payload-{version}"
    (artifact / "nested").mkdir(parents=True)
    (artifact / "VERSION").write_text(version, encoding="utf-8")
    (artifact / "nested" / "app.txt").write_text(f"app-{version}", encoding="utf-8")
    files, size, digest = directory_sha256(artifact)
    assert files == 2
    return artifact, UpdateManifest(version, "payload", digest, size)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact", "../outside"),
        ("artifact", "C:\\outside"),
        ("sha256", "A" * 64),
        ("sha256", "not-a-digest"),
        ("size_bytes", 0),
        ("size_bytes", "12"),
        ("max_files", 0),
        ("max_unpacked_bytes", 0),
    ],
)
def test_manifest_rejects_unsafe_or_malformed_values(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "version": "1.2.3",
        "artifact": "payload",
        "sha256": "a" * 64,
        "size_bytes": 12,
    }
    payload[field] = value

    with pytest.raises(ManifestError):
        UpdateManifest.from_dict(payload)


def test_manifest_file_is_local_and_strict(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "schema_version": 1,
            "version": "2.0.0",
            "artifact": "payload",
            "sha256": "b" * 64,
            "size_bytes": 12,
        }),
        encoding="utf-8",
    )

    manifest = UpdateManifest.from_file(manifest_path)

    assert manifest.version == "2.0.0"
    assert manifest.artifact == "payload"


def test_stage_requires_matching_bounded_manifest(tmp_path: Path) -> None:
    artifact, manifest = _artifact(tmp_path, "1.0.0")
    contract = UpdateContract(tmp_path / "install")

    staged = contract.stage(manifest, artifact)

    assert staged.manifest == manifest
    assert (contract.slots / ".staging" / "VERSION").read_text() == "1.0.0"
    assert (contract.root / "update-state.json").exists()

    with pytest.raises(ManifestError, match="SHA-256"):
        contract.stage(
            UpdateManifest("1.0.0", "payload", "c" * 64, manifest.size_bytes),
            artifact,
        )


def test_activation_preserves_previous_slot_and_rollback_is_atomic(
    tmp_path: Path,
) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / "config.json").write_text("preserve", encoding="utf-8")
    contract = UpdateContract(install)

    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    first = contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    second = contract.activate(contract.stage(second_manifest, second_artifact))

    assert contract.current() == second
    assert second.previous_slot == first.active_slot
    assert (contract.slots / second.previous_slot / "VERSION").read_text() == "1.0.0"
    assert (install / "config.json").read_text() == "preserve"

    rolled_back = contract.rollback()

    assert rolled_back.active_slot == first.active_slot
    assert rolled_back.version == "1.0.0"
    assert rolled_back.previous_slot == second.active_slot
    assert (
        contract.slots / rolled_back.previous_slot / "VERSION"
    ).read_text() == "2.0.0"
    assert not contract.state_path.exists()


@pytest.mark.parametrize("boundary", ["state", "pointer", "commit"])
def test_interrupted_activation_recovers_at_each_boundary(
    tmp_path: Path, boundary: str
) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    first = contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    staged = contract.stage(second_manifest, second_artifact)

    with pytest.raises(UpdateInterrupted):
        contract.activate(staged, interrupt_after=boundary)

    recovered = contract.recover_interrupted()
    assert recovered is not None
    assert not contract.state_path.exists()
    assert not (contract.slots / ".staging").exists()
    assert contract.recover_interrupted() == recovered

    if boundary == "state":
        assert recovered.active_slot == first.active_slot
        assert recovered.version == "1.0.0"
    else:
        assert recovered.version == "2.0.0"
        assert recovered.previous_slot == first.active_slot
        assert (contract.slots / first.active_slot / "VERSION").read_text() == "1.0.0"


def test_failed_health_check_rolls_back_without_losing_previous(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    first = contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")

    with pytest.raises(UpdateError, match="rolled back"):
        contract.activate(
            contract.stage(second_manifest, second_artifact),
            health_check=lambda _candidate: False,
        )

    current = contract.current()
    assert current is not None
    assert current.active_slot == first.active_slot
    assert current.version == first.version
    assert not contract.state_path.exists()
