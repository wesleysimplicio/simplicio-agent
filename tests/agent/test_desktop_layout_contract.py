"""Focused tests for the bounded issue #126 Desktop layout contract."""

from __future__ import annotations

from agent.desktop_layout_contract import (
    CANONICAL_DESKTOP_ROOT,
    LEGACY_DESKTOP_ROOT,
    DEFAULT_SURFACE_MAPPINGS,
    DesktopLayoutContract,
    DriftCode,
    MigrationStatus,
    PathOwner,
    PathOwnership,
    RootRole,
    RootSpec,
    SurfaceMapping,
    DesktopSurface,
    detect_desktop_path_drift,
    resolve_desktop_path,
)


def test_default_layout_declares_canonical_and_legacy_roots_without_migration_claim():
    contract = DesktopLayoutContract()

    assert contract.canonical_root == CANONICAL_DESKTOP_ROOT
    assert contract.legacy_roots == (LEGACY_DESKTOP_ROOT,)
    assert len(contract.surfaces) == len(DEFAULT_SURFACE_MAPPINGS)
    report = contract.detect_drift({})
    assert report.is_fully_migrated is False
    assert report.can_claim_full_migration is False
    assert report.migration_proof == "not_proven"


def test_unique_canonical_path_is_safe_only_with_unambiguous_ownership():
    resolution = resolve_desktop_path("apps\\desktop\\src\\main.tsx")

    assert resolution.normalised_path == "apps/desktop/src/main.tsx"
    assert resolution.status is MigrationStatus.MIGRATED
    assert resolution.root_role is RootRole.CANONICAL
    assert resolution.owner is PathOwner.DESKTOP_SOURCE
    assert resolution.is_safe


def test_legacy_path_is_pending_and_unknown_path_is_drifted():
    contract = DesktopLayoutContract()

    legacy = contract.resolve_path("desktop/src/main.tsx")
    unknown = contract.resolve_path("apps/desktop-old/src/main.tsx")

    assert legacy.status is MigrationStatus.PENDING
    assert legacy.reason is DriftCode.LEGACY_PATH
    assert not legacy.is_safe
    assert unknown.status is MigrationStatus.DRIFTED
    assert unknown.reason is DriftCode.UNKNOWN_PATH


def test_ambiguous_root_and_owner_inputs_fail_closed():
    overlapping = DesktopLayoutContract(
        roots=(
            RootSpec("apps/desktop", RootRole.CANONICAL),
            RootSpec("apps/desktop/src", RootRole.LEGACY),
        ),
    )
    ambiguous_owner = DesktopLayoutContract(
        ownership=(
            PathOwnership(CANONICAL_DESKTOP_ROOT, PathOwner.DESKTOP_SOURCE),
            PathOwnership("apps/desktop/src", PathOwner.WORKSPACE),
        ),
    )

    root_result = overlapping.resolve_path("apps/desktop/src/main.tsx")
    owner_result = ambiguous_owner.resolve_path("apps/desktop/src/main.tsx")

    assert root_result.status is MigrationStatus.AMBIGUOUS
    assert root_result.reason is DriftCode.CONFIGURATION_AMBIGUOUS
    assert root_result.owner is None
    assert owner_result.status is MigrationStatus.AMBIGUOUS
    assert owner_result.reason is DriftCode.OWNER_AMBIGUOUS
    assert owner_result.is_safe is False


def test_invalid_and_absolute_paths_fail_closed_without_path_resolution():
    contract = DesktopLayoutContract()

    for path in ("../desktop", "/apps/desktop", r"C:\apps\desktop", "apps//desktop"):
        result = contract.resolve_path(path)
        assert result.status is MigrationStatus.DRIFTED
        assert result.reason is DriftCode.INVALID_PATH
        assert result.owner is None


def test_surface_drift_distinguishes_canonical_legacy_unknown_and_missing():
    observed = {
        DesktopSurface.WORKSPACE: "apps/desktop/package.json",
        DesktopSurface.CI: "desktop/package.json",
        DesktopSurface.INSTALLER: "some/other/path",
    }

    report = detect_desktop_path_drift(observed)

    assert report.statuses[DesktopSurface.WORKSPACE.value] is MigrationStatus.MIGRATED
    assert report.statuses[DesktopSurface.CI.value] is MigrationStatus.PENDING
    assert report.statuses[DesktopSurface.INSTALLER.value] is MigrationStatus.DRIFTED
    assert report.statuses[DesktopSurface.RELEASE.value] is MigrationStatus.UNDECLARED
    assert report.has_drift
    assert report.observed_paths_are_canonical is False
    assert any(item.code is DriftCode.LEGACY_PATH for item in report.findings)
    assert any(item.code is DriftCode.MISSING_PATH for item in report.findings)


def test_all_observed_surfaces_can_be_canonical_without_claiming_full_rollout():
    observed = {
        surface: f"apps/desktop/consumer/{surface.value}.json"
        for surface in DesktopSurface
    }

    report = DesktopLayoutContract().audit(observed, include_missing=True)

    assert report.findings == ()
    assert report.observed_paths_are_canonical
    assert report.is_fully_migrated is False
    assert report.as_dict()["fully_migrated"] is False
    assert report.to_json() == report.to_json()


def test_duplicate_surface_mapping_is_ambiguous_and_never_selects_a_consumer():
    contract = DesktopLayoutContract(
        surfaces=(
            SurfaceMapping(DesktopSurface.CLI, PathOwner.CLI),
            SurfaceMapping(DesktopSurface.CLI, PathOwner.WORKSPACE),
        )
    )

    result = contract.resolve_surface(DesktopSurface.CLI, "apps/desktop/cli.ts")
    report = contract.detect_drift({DesktopSurface.CLI: "apps/desktop/cli.ts"}, include_missing=False)

    assert result.migration_status is MigrationStatus.AMBIGUOUS
    assert result.reason is DriftCode.AMBIGUOUS_PATH
    assert report.findings[0].status is MigrationStatus.AMBIGUOUS
