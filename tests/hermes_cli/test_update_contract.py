"""Focused local tests for the issue #129 staged-update contract."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hermes_cli.update_contract import (
    COMPATIBILITY_SCHEMA,
    COMPATIBILITY_VERSION,
    CompatibilityMatrix,
    ManifestError,
    UpdateContract,
    UpdateError,
    UpdateInterrupted,
    UpdateManifest,
    UpdatePlan,
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


def _matrix(*rows: dict[str, object]) -> CompatibilityMatrix:
    return CompatibilityMatrix.from_dict(
        {
            "schema": COMPATIBILITY_SCHEMA,
            "version": COMPATIBILITY_VERSION,
            "rows": list(rows),
        }
    )


def _compatible_plan(
    contract: UpdateContract, manifest: UpdateManifest
) -> tuple[CompatibilityMatrix, UpdatePlan]:
    current = contract.current()
    assert current is not None
    matrix = _matrix(
        {
            "from_version": current.version,
            "to_version": manifest.version,
            "supported": True,
        }
    )
    return matrix, contract.plan(manifest, matrix)


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
    matrix, plan = _compatible_plan(contract, second_manifest)
    second = contract.activate(
        contract.stage(second_manifest, second_artifact),
        plan=plan,
        matrix=matrix,
    )

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
    matrix, plan = _compatible_plan(contract, second_manifest)
    staged = contract.stage(second_manifest, second_artifact)

    with pytest.raises(UpdateInterrupted):
        contract.activate(
            staged,
            plan=plan,
            matrix=matrix,
            interrupt_after=boundary,
        )

    restarted = UpdateContract(contract.root)
    recovered = restarted.current()
    assert recovered is not None
    assert not restarted.state_path.exists()
    assert not (restarted.slots / ".staging").exists()
    assert restarted.recover_interrupted() == recovered

    if boundary == "state":
        assert recovered.active_slot == first.active_slot
        assert recovered.version == "1.0.0"
    else:
        assert recovered.version == "2.0.0"
        assert recovered.previous_slot == first.active_slot
        assert (restarted.slots / first.active_slot / "VERSION").read_text() == "1.0.0"


def test_failed_health_check_rolls_back_without_losing_previous(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    first = contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    matrix, plan = _compatible_plan(contract, second_manifest)

    with pytest.raises(UpdateError, match="rolled back"):
        contract.activate(
            contract.stage(second_manifest, second_artifact),
            plan=plan,
            matrix=matrix,
            health_check=lambda _candidate: False,
        )

    current = contract.current()
    assert current is not None
    assert current.active_slot == first.active_slot
    assert current.version == first.version
    assert not contract.state_path.exists()


def test_plan_rejects_incompatible_downgrade(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    setup_matrix, setup_plan = _compatible_plan(contract, second_manifest)
    contract.activate(
        contract.stage(second_manifest, second_artifact),
        plan=setup_plan,
        matrix=setup_matrix,
    )

    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2"],
        },
        {
            "from_version": "2.0.0",
            "to_version": "1.0.0",
            "supported": False,
            "notes": "downgrade requires clean-machine restore",
        },
    )

    plan = contract.plan(first_manifest, matrix)

    assert plan.allowed is False
    assert plan.direction == "downgrade"
    assert plan.reason == "incompatible_transition"
    assert "clean-machine restore" in plan.notes


def test_matrix_round_trip_preserves_migration_rollback_contract() -> None:
    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2", "ledger-v1"],
            "rollback_migration_ids": ["settings-v1", "ledger-v1-undo"],
        }
    )

    encoded = matrix.to_dict()

    assert encoded["rows"][0]["rollback_migration_ids"] == [
        "settings-v1",
        "ledger-v1-undo",
    ]
    assert CompatibilityMatrix.from_dict(encoded) == matrix


def test_migration_rollback_contract_uses_a_new_schema_version() -> None:
    assert COMPATIBILITY_SCHEMA == "simplicio.update-compatibility/v2"
    assert COMPATIBILITY_VERSION == 2

    with pytest.raises(UpdateError, match="unsupported compatibility schema"):
        CompatibilityMatrix.from_dict(
            {
                "schema": "simplicio.update-compatibility/v1",
                "version": 1,
                "rows": [],
            }
        )


def test_plan_blocks_migration_without_rollback_contract(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    _, second_manifest = _artifact(tmp_path, "2.0.0")
    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2"],
        }
    )

    plan = contract.plan(second_manifest, matrix)

    assert plan.allowed is False
    assert plan.reason == "migration_rollback_undefined"
    assert plan.rollback_available is False
    assert plan.to_dict()["rollback_migration_ids"] == []


def test_blocked_migration_plan_reports_existing_slot_rollback(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    setup_matrix, setup_plan = _compatible_plan(contract, second_manifest)
    contract.activate(
        contract.stage(second_manifest, second_artifact),
        plan=setup_plan,
        matrix=setup_matrix,
    )
    _, third_manifest = _artifact(tmp_path, "3.0.0")
    matrix = _matrix(
        {
            "from_version": "2.0.0",
            "to_version": "3.0.0",
            "supported": True,
            "migration_ids": ["settings-v3"],
        }
    )

    plan = contract.plan(third_manifest, matrix)

    assert plan.allowed is False
    assert plan.reason == "migration_rollback_undefined"
    assert plan.rollback_available is True


def test_allowed_plan_cannot_bypass_migration_rollback_contract() -> None:
    with pytest.raises(UpdateError, match="one-to-one rollback"):
        UpdatePlan(
            current_version="1.0.0",
            target_version="2.0.0",
            direction="upgrade",
            allowed=True,
            migration_ids=("settings-v2",),
            rollback_migration_ids=(),
            blocked_effects=(),
            rollback_available=False,
            reason="compatible",
        )


def test_existing_install_activation_requires_matrix_bound_plan(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    staged = contract.stage(second_manifest, second_artifact)

    with pytest.raises(UpdateError, match="compatibility plan and matrix"):
        contract.activate(staged)


def test_activation_rejects_plan_that_does_not_match_matrix(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2"],
            "rollback_migration_ids": ["settings-v1"],
        }
    )
    plan = contract.plan(second_manifest, matrix)
    forged = replace(
        plan,
        migration_ids=("unlisted-migration",),
        rollback_migration_ids=("unlisted-rollback",),
    )
    staged = contract.stage(second_manifest, second_artifact)

    with pytest.raises(UpdateError, match="does not match the compatibility matrix"):
        contract.activate(staged, plan=forged, matrix=matrix)


def test_plan_tracks_idempotent_migrations_across_activation(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2", "ledger-v1"],
            "rollback_migration_ids": ["settings-v1", "ledger-v1-undo"],
        },
        {
            "from_version": "2.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2", "ledger-v1"],
            "rollback_migration_ids": ["settings-v1", "ledger-v1-undo"],
        },
    )

    first_plan = contract.plan(second_manifest, matrix)
    record = contract.activate(
        contract.stage(second_manifest, second_artifact),
        plan=first_plan,
        matrix=matrix,
    )
    second_plan = contract.plan(second_manifest, matrix)

    assert first_plan.allowed is True
    assert first_plan.rollback_available is False
    assert first_plan.migration_ids == ("settings-v2", "ledger-v1")
    assert first_plan.rollback_migration_ids == (
        "ledger-v1-undo",
        "settings-v1",
    )
    assert record.applied_migrations == ("settings-v2", "ledger-v1")
    assert record.rollback_migration_ids == ("ledger-v1-undo", "settings-v1")
    assert second_plan.allowed is True
    assert second_plan.direction == "noop"
    assert second_plan.migration_ids == ()
    assert second_plan.rollback_migration_ids == ()

    rolled_back = contract.rollback()

    assert rolled_back.applied_migrations == ()
    assert rolled_back.previous_applied_migrations == ("settings-v2", "ledger-v1")
    assert rolled_back.rollback_migration_ids == ("settings-v2", "ledger-v1")

    restored = contract.rollback()

    assert restored.applied_migrations == ("settings-v2", "ledger-v1")
    assert restored.rollback_migration_ids == (
        "ledger-v1-undo",
        "settings-v1",
    )


def test_rollback_rejects_partial_persisted_migration_contract(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2", "ledger-v1"],
            "rollback_migration_ids": ["settings-v1", "ledger-v1-undo"],
        }
    )
    plan = contract.plan(second_manifest, matrix)
    active = contract.activate(
        contract.stage(second_manifest, second_artifact),
        plan=plan,
        matrix=matrix,
    )
    record = json.loads(contract.active_path.read_text(encoding="utf-8"))
    record["rollback_migration_ids"] = ["settings-v1"]
    contract.active_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(UpdateError, match="one-to-one"):
        contract.rollback()

    assert json.loads(contract.active_path.read_text(encoding="utf-8"))[
        "active_slot"
    ] == active.active_slot


def test_legacy_migrated_record_is_readable_but_rollback_fails_closed(
    tmp_path: Path,
) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["settings-v2"],
            "rollback_migration_ids": ["settings-v1"],
        }
    )
    plan = contract.plan(second_manifest, matrix)
    active = contract.activate(
        contract.stage(second_manifest, second_artifact),
        plan=plan,
        matrix=matrix,
    )
    record = json.loads(contract.active_path.read_text(encoding="utf-8"))
    del record["rollback_migration_ids"]
    del record["previous_rollback_migration_ids"]
    contract.active_path.write_text(json.dumps(record), encoding="utf-8")

    legacy = contract.current()

    assert legacy is not None
    assert legacy.active_slot == active.active_slot
    assert legacy.rollback_migration_ids == ()
    with pytest.raises(UpdateError, match="migration rollback contract is missing"):
        contract.rollback()


def test_plan_blocks_effects_while_runtime_work_is_in_flight(tmp_path: Path) -> None:
    contract = UpdateContract(tmp_path / "install")
    first_artifact, first_manifest = _artifact(tmp_path, "1.0.0")
    contract.activate(contract.stage(first_manifest, first_artifact))
    second_artifact, second_manifest = _artifact(tmp_path, "2.0.0")
    matrix = _matrix(
        {
            "from_version": "1.0.0",
            "to_version": "2.0.0",
            "supported": True,
            "migration_ids": ["ledger-v1"],
            "rollback_migration_ids": ["ledger-v1-undo"],
            "blocked_effects": ["runtime-session", "gateway-turn"],
        }
    )

    blocked = contract.plan(
        second_manifest,
        matrix,
        in_flight_effects=("runtime-session",),
    )
    allowed = contract.plan(
        second_manifest,
        matrix,
        in_flight_effects=("unrelated-effect",),
    )

    assert blocked.allowed is False
    assert blocked.reason == "blocked_in_flight_effects"
    assert blocked.blocked_effects == ("runtime-session",)
    assert allowed.allowed is True
    assert allowed.migration_ids == ("ledger-v1",)
