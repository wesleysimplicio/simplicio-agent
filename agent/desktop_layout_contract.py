"""Bounded, additive Desktop layout and path contract for issue #126.

This module describes the intended Desktop layout; it does not move files,
rewrite consumers, run a build, or inspect the repository.  The default
contract records the proposed ``apps/desktop`` canonical root and the current
``desktop`` legacy root.  A caller may audit observed consumer paths, but an
audit can never claim that every Desktop consumer has been migrated.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Final, Mapping


ISSUE_NUMBER: Final = 126
DESKTOP_LAYOUT_CONTRACT_SCHEMA: Final = "simplicio-agent/desktop-layout-contract/v1"
CANONICAL_DESKTOP_ROOT: Final = "apps/desktop"
LEGACY_DESKTOP_ROOT: Final = "desktop"
MAX_ROOTS: Final = 8
MAX_SURFACES: Final = 32
MAX_PATH_LENGTH: Final = 4096


def _normalise_relative_path(path: object, label: str) -> str:
    if not isinstance(path, str):
        raise TypeError(f"{label} must be a string")
    if not path or len(path) > MAX_PATH_LENGTH or "\x00" in path:
        raise ValueError(f"{label} is invalid")
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"{label} must be relative")
    normalised = path.replace("\\", "/")
    parts = normalised.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} contains ambiguous segments")
    return "/".join(parts)


def _enum_value(value: object, enum_type: type[StrEnum], label: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc


def _path_matches(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _paths_overlap(left: str, right: str) -> bool:
    return _path_matches(left, right) or _path_matches(right, left)


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


class RootRole(StrEnum):
    """Role assigned to a root in one layout declaration."""

    CANONICAL = "canonical"
    LEGACY = "legacy"


class PathOwner(StrEnum):
    """Logical owner of a Desktop layout path or consumer surface."""

    DESKTOP_SOURCE = "desktop_source"
    WORKSPACE = "workspace"
    CI = "ci"
    INSTALLER = "installer"
    RELEASE = "release"
    CLI = "cli"
    UPDATE = "update"
    RELAUNCH = "relaunch"
    DOCS = "docs"


class DesktopSurface(StrEnum):
    """Consumers that must agree on the Desktop root."""

    WORKSPACE = "workspace"
    CI = "ci"
    INSTALLER = "installer"
    RELEASE = "release"
    CLI = "cli"
    UPDATE = "update"
    RELAUNCH = "relaunch"
    DOCS = "docs"


class MigrationStatus(StrEnum):
    """Status of an observed path, deliberately distinct from proof of rollout."""

    MIGRATED = "migrated"
    CANONICAL = "migrated"  # compatibility spelling for path classification
    PENDING = "pending"
    LEGACY = "pending"  # compatibility spelling for path classification
    DRIFTED = "drifted"
    UNKNOWN = "drifted"  # compatibility spelling for path classification
    AMBIGUOUS = "ambiguous"
    UNDECLARED = "undeclared"


class DriftCode(StrEnum):
    """Stable, fail-closed reasons emitted by the audit."""

    CANONICAL_PATH = "canonical_path"
    LEGACY_PATH = "legacy_path"
    UNKNOWN_PATH = "unknown_path"
    INVALID_PATH = "invalid_path"
    AMBIGUOUS_PATH = "ambiguous_path"
    OWNER_AMBIGUOUS = "owner_ambiguous"
    UNKNOWN_SURFACE = "unknown_surface"
    MISSING_PATH = "missing_path"
    CONFIGURATION_AMBIGUOUS = "configuration_ambiguous"


@dataclass(frozen=True, slots=True)
class RootSpec:
    """One relative root and its role in a layout."""

    path: str
    role: RootRole

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalise_relative_path(self.path, "root"))
        object.__setattr__(self, "role", _enum_value(self.role, RootRole, "root role"))


@dataclass(frozen=True, slots=True)
class PathOwnership:
    """Ownership declaration for one path prefix.

    Ownership is intentionally separate from surface mapping: one Desktop
    source root has one owner, while several consumers may point at it.
    """

    path: str
    owner: PathOwner

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalise_relative_path(self.path, "ownership path"))
        object.__setattr__(self, "owner", _enum_value(self.owner, PathOwner, "path owner"))


@dataclass(frozen=True, slots=True)
class SurfaceMapping:
    """Expected canonical and legacy roots for one Desktop consumer."""

    surface: DesktopSurface
    owner: PathOwner
    canonical_root: str = CANONICAL_DESKTOP_ROOT
    legacy_roots: tuple[str, ...] = (LEGACY_DESKTOP_ROOT,)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "surface",
            _enum_value(self.surface, DesktopSurface, "surface"),
        )
        object.__setattr__(self, "owner", _enum_value(self.owner, PathOwner, "surface owner"))
        object.__setattr__(
            self,
            "canonical_root",
            _normalise_relative_path(self.canonical_root, "canonical surface root"),
        )
        normalised_legacy = tuple(
            _normalise_relative_path(path, "legacy surface root") for path in self.legacy_roots
        )
        object.__setattr__(self, "legacy_roots", _unique(normalised_legacy))


@dataclass(frozen=True, slots=True)
class PathResolution:
    """Non-throwing classification of an observed path."""

    input_path: str
    normalised_path: str | None
    matched_roots: tuple[str, ...]
    root_role: RootRole | None
    owner: PathOwner | None
    status: MigrationStatus
    reason: DriftCode | None = None

    @property
    def is_safe(self) -> bool:
        """Only a unique canonical path with an unambiguous owner is safe."""

        return (
            self.status is MigrationStatus.MIGRATED
            and self.root_role is RootRole.CANONICAL
            and self.owner is not None
        )

    @property
    def path(self) -> str | None:
        """Compatibility alias for the normalised path."""

        return self.normalised_path

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["root_role"] = self.root_role.value if self.root_role else None
        data["owner"] = self.owner.value if self.owner else None
        data["status"] = self.status.value
        data["reason"] = self.reason.value if self.reason else None
        return data


@dataclass(frozen=True, slots=True)
class SurfaceResolution:
    """Classification of one consumer's observed path."""

    surface: str
    observed_path: str | None
    expected_canonical_root: str | None
    migration_status: MigrationStatus
    reason: DriftCode | None = None

    @property
    def is_canonical(self) -> bool:
        return self.migration_status is MigrationStatus.MIGRATED

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["migration_status"] = self.migration_status.value
        data["reason"] = self.reason.value if self.reason else None
        return data


@dataclass(frozen=True, slots=True)
class DriftFinding:
    """One actionable discrepancy without pretending to fix it."""

    surface: str
    status: MigrationStatus
    code: DriftCode
    observed_path: str | None
    expected_path: str | None
    detail: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        data["code"] = self.code.value
        return data


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """Bounded audit output with an explicit no-rollout-proof boundary."""

    issue_number: int
    schema: str
    statuses: Mapping[str, MigrationStatus]
    findings: tuple[DriftFinding, ...]
    observed_surface_count: int
    fully_migrated: bool = False
    migration_proof: str = "not_proven"

    @property
    def has_drift(self) -> bool:
        return bool(self.findings)

    @property
    def is_fully_migrated(self) -> bool:
        """This additive contract never claims all consumers were migrated."""

        return False

    @property
    def can_claim_full_migration(self) -> bool:
        return False

    @property
    def observed_paths_are_canonical(self) -> bool:
        return bool(self.statuses) and all(
            status is MigrationStatus.MIGRATED for status in self.statuses.values()
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "schema": self.schema,
            "statuses": {
                name: status.value for name, status in sorted(self.statuses.items())
            },
            "findings": [finding.as_dict() for finding in self.findings],
            "observed_surface_count": self.observed_surface_count,
            "fully_migrated": False,
            "migration_proof": self.migration_proof,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


DEFAULT_ROOTS: Final[tuple[RootSpec, ...]] = (
    RootSpec(CANONICAL_DESKTOP_ROOT, RootRole.CANONICAL),
    RootSpec(LEGACY_DESKTOP_ROOT, RootRole.LEGACY),
)
DEFAULT_OWNERSHIP: Final[tuple[PathOwnership, ...]] = (
    PathOwnership(CANONICAL_DESKTOP_ROOT, PathOwner.DESKTOP_SOURCE),
)
DEFAULT_SURFACE_MAPPINGS: Final[tuple[SurfaceMapping, ...]] = tuple(
    SurfaceMapping(surface, PathOwner(surface.value)) for surface in DesktopSurface
)


@dataclass(frozen=True, slots=True)
class DesktopLayoutContract:
    """Pure layout declaration and fail-closed path auditor for issue #126."""

    roots: tuple[RootSpec, ...] = DEFAULT_ROOTS
    ownership: tuple[PathOwnership, ...] = DEFAULT_OWNERSHIP
    surfaces: tuple[SurfaceMapping, ...] = DEFAULT_SURFACE_MAPPINGS
    issue_number: int = ISSUE_NUMBER

    def __post_init__(self) -> None:
        roots = tuple(self.roots)
        ownership = tuple(self.ownership)
        surfaces = tuple(self.surfaces)
        if len(roots) > MAX_ROOTS:
            raise ValueError(f"at most {MAX_ROOTS} roots are supported")
        if len(surfaces) > MAX_SURFACES:
            raise ValueError(f"at most {MAX_SURFACES} surfaces are supported")
        object.__setattr__(self, "roots", roots)
        object.__setattr__(self, "ownership", ownership)
        object.__setattr__(self, "surfaces", surfaces)

    @property
    def canonical_root(self) -> str | None:
        canonical = {root.path for root in self.roots if root.role is RootRole.CANONICAL}
        return next(iter(canonical)) if len(canonical) == 1 else None

    @property
    def legacy_roots(self) -> tuple[str, ...]:
        return tuple(
            sorted({root.path for root in self.roots if root.role is RootRole.LEGACY})
        )

    def configuration_errors(self) -> tuple[str, ...]:
        """Return deterministic configuration problems without selecting a path."""

        errors: list[str] = []
        root_paths = [root.path for root in self.roots]
        if len(set(root_paths)) != len(root_paths):
            errors.append("duplicate root path")
        if len([root for root in self.roots if root.role is RootRole.CANONICAL]) != 1:
            errors.append("exactly one canonical root is required")
        for index, left in enumerate(self.roots):
            for right in self.roots[index + 1 :]:
                if _paths_overlap(left.path, right.path):
                    errors.append(f"overlapping roots: {left.path} and {right.path}")
        ownership_paths = [item.path for item in self.ownership]
        if len(set(ownership_paths)) != len(ownership_paths):
            errors.append("ambiguous path ownership")
        surface_names = [item.surface.value for item in self.surfaces]
        if len(set(surface_names)) != len(surface_names):
            errors.append("ambiguous surface mapping")
        return tuple(sorted(set(errors)))

    def resolve_path(self, path: object) -> PathResolution:
        """Classify a path; invalid, unknown, and ambiguous inputs fail closed."""

        raw = path if isinstance(path, str) else ""
        try:
            normalised = _normalise_relative_path(path, "observed path")
        except (TypeError, ValueError):
            return PathResolution(
                raw,
                None,
                (),
                None,
                None,
                MigrationStatus.DRIFTED,
                DriftCode.INVALID_PATH,
            )

        if self.configuration_errors():
            return PathResolution(
                raw,
                normalised,
                (),
                None,
                None,
                MigrationStatus.AMBIGUOUS,
                DriftCode.CONFIGURATION_AMBIGUOUS,
            )

        matches = tuple(root for root in self.roots if _path_matches(normalised, root.path))
        if len(matches) != 1:
            return PathResolution(
                raw,
                normalised,
                tuple(root.path for root in matches),
                None,
                None,
                MigrationStatus.AMBIGUOUS if matches else MigrationStatus.DRIFTED,
                DriftCode.AMBIGUOUS_PATH if matches else DriftCode.UNKNOWN_PATH,
            )

        root = matches[0]
        owner_matches = tuple(
            item for item in self.ownership if _path_matches(normalised, item.path)
        )
        owner: PathOwner | None = None
        if len(owner_matches) == 1:
            owner = owner_matches[0].owner
        elif len(owner_matches) > 1:
            return PathResolution(
                raw,
                normalised,
                (root.path,),
                root.role,
                None,
                MigrationStatus.AMBIGUOUS,
                DriftCode.OWNER_AMBIGUOUS,
            )

        return PathResolution(
            raw,
            normalised,
            (root.path,),
            root.role,
            owner,
            MigrationStatus.MIGRATED
            if root.role is RootRole.CANONICAL
            else MigrationStatus.PENDING,
            DriftCode.CANONICAL_PATH
            if root.role is RootRole.CANONICAL
            else DriftCode.LEGACY_PATH,
        )

    def owner_for(self, path: object) -> PathOwner | None:
        """Return an owner only for a unique canonical path; otherwise ``None``."""

        resolution = self.resolve_path(path)
        return resolution.owner if resolution.is_safe else None

    def resolve_surface(self, surface: object, path: object) -> SurfaceResolution:
        """Classify one consumer path against its unique surface mapping."""

        name = surface.value if isinstance(surface, DesktopSurface) else str(surface)
        mappings = tuple(item for item in self.surfaces if item.surface.value == name)
        if len(mappings) != 1:
            return SurfaceResolution(
                name,
                path if isinstance(path, str) else None,
                None,
                MigrationStatus.AMBIGUOUS if mappings else MigrationStatus.DRIFTED,
                DriftCode.AMBIGUOUS_PATH if mappings else DriftCode.UNKNOWN_SURFACE,
            )

        mapping = mappings[0]
        resolution = self.resolve_path(path)
        if resolution.normalised_path is None:
            return SurfaceResolution(
                name,
                path if isinstance(path, str) else None,
                mapping.canonical_root,
                MigrationStatus.DRIFTED,
                DriftCode.INVALID_PATH,
            )
        if resolution.status is MigrationStatus.AMBIGUOUS:
            return SurfaceResolution(
                name,
                resolution.normalised_path,
                mapping.canonical_root,
                MigrationStatus.AMBIGUOUS,
                resolution.reason or DriftCode.AMBIGUOUS_PATH,
            )
        if _path_matches(resolution.normalised_path, mapping.canonical_root):
            return SurfaceResolution(
                name,
                resolution.normalised_path,
                mapping.canonical_root,
                MigrationStatus.MIGRATED,
                DriftCode.CANONICAL_PATH,
            )
        if any(_path_matches(resolution.normalised_path, root) for root in mapping.legacy_roots):
            return SurfaceResolution(
                name,
                resolution.normalised_path,
                mapping.canonical_root,
                MigrationStatus.PENDING,
                DriftCode.LEGACY_PATH,
            )
        return SurfaceResolution(
            name,
            resolution.normalised_path,
            mapping.canonical_root,
            MigrationStatus.DRIFTED,
            DriftCode.UNKNOWN_PATH,
        )

    def detect_drift(
        self,
        observed_paths: Mapping[object, object],
        *,
        include_missing: bool = True,
    ) -> MigrationReport:
        """Audit observed consumer paths without editing or claiming rollout."""

        if not isinstance(observed_paths, Mapping):
            observed_paths = {}

        findings: list[DriftFinding] = []
        statuses: dict[str, MigrationStatus] = {}
        known = {mapping.surface.value for mapping in self.surfaces}
        for surface, path in observed_paths.items():
            name = surface.value if isinstance(surface, DesktopSurface) else str(surface)
            resolution = self.resolve_surface(surface, path)
            statuses[name] = resolution.migration_status
            if resolution.migration_status is not MigrationStatus.MIGRATED:
                findings.append(
                    DriftFinding(
                        name,
                        resolution.migration_status,
                        resolution.reason or DriftCode.UNKNOWN_PATH,
                        resolution.observed_path,
                        resolution.expected_canonical_root,
                        _detail_for(resolution),
                    )
                )

        if include_missing:
            for name in sorted(known - set(statuses)):
                mapping = next(item for item in self.surfaces if item.surface.value == name)
                statuses[name] = MigrationStatus.UNDECLARED
                findings.append(
                    DriftFinding(
                        name,
                        MigrationStatus.UNDECLARED,
                        DriftCode.MISSING_PATH,
                        None,
                        mapping.canonical_root,
                        "no observed consumer path was supplied",
                    )
                )

        return MigrationReport(
            self.issue_number,
            DESKTOP_LAYOUT_CONTRACT_SCHEMA,
            statuses,
            tuple(findings),
            len(observed_paths),
        )

    audit = detect_drift


def resolve_desktop_path(path: object, contract: DesktopLayoutContract | None = None) -> PathResolution:
    """Convenience wrapper for callers that use the default layout."""

    return (contract or DesktopLayoutContract()).resolve_path(path)


def detect_desktop_path_drift(
    observed_paths: Mapping[object, object],
    *,
    contract: DesktopLayoutContract | None = None,
    include_missing: bool = True,
) -> MigrationReport:
    """Convenience wrapper for the bounded default audit."""

    return (contract or DesktopLayoutContract()).detect_drift(
        observed_paths,
        include_missing=include_missing,
    )


def _detail_for(resolution: SurfaceResolution) -> str:
    if resolution.reason is DriftCode.LEGACY_PATH:
        return "consumer still points at a legacy Desktop root"
    if resolution.reason is DriftCode.MISSING_PATH:
        return "consumer path is missing"
    if resolution.reason is DriftCode.AMBIGUOUS_PATH:
        return "multiple roots or mappings match; refusing to choose one"
    if resolution.reason is DriftCode.INVALID_PATH:
        return "path is invalid or not safely relative"
    if resolution.reason is DriftCode.UNKNOWN_SURFACE:
        return "surface is not declared by the contract"
    return "consumer path does not match the declared canonical root"


# Short aliases keep the public contract discoverable without duplicating types.
CanonicalRoot = RootSpec
SurfacePathMapping = SurfaceMapping
MigrationAudit = MigrationReport
