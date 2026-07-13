"""Deterministic contract for the repository's desktop application layout.

The canonical desktop root is desktop/. apps/desktop/ is accepted only as a
legacy fallback. A repository containing both roots is ambiguous and a
repository containing neither root is invalid.

Only caller-selected manifest/consumer files are scanned for stale
apps/desktop references; the whole tree is not grepped. npm build proof and
installer proof remain unverified: this module never runs npm or installers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

DESKTOP_LAYOUT_SCHEMA = "simplicio-agent/desktop-layout-receipt/v1"
DESKTOP_LAYOUT_VERSION = 1
CANONICAL_DESKTOP_DIRECTORY = "desktop"
LEGACY_DESKTOP_DIRECTORY = "apps/desktop"
STALE_DESKTOP_REFERENCE = LEGACY_DESKTOP_DIRECTORY
_STALE_DESKTOP_PATTERN = re.compile(r"apps[\\/]desktop", re.IGNORECASE)

DEFAULT_SELECTED_MANIFESTS = (
    ".envrc",
    ".github/workflows/typecheck.yml",
    "package.json",
)

ProofState = Literal["unverified"]


class DesktopLayoutContractError(ValueError):
    """Base class for invalid desktop layout contracts."""


class DesktopLayoutMissingError(DesktopLayoutContractError):
    """Raised when a repository has no usable desktop root."""


class DesktopLayoutAmbiguousError(DesktopLayoutContractError):
    """Raised when both canonical and legacy desktop roots exist."""


@dataclass(frozen=True)
class StaleDesktopReference:
    """One stale legacy-root reference found in a selected manifest."""

    path: str
    line: int
    column: int
    reference: str = STALE_DESKTOP_REFERENCE
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "reference": self.reference,
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class UnverifiedProof:
    """A deliberately unrun proof step recorded in the receipt."""

    status: ProofState
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class DesktopLayout:
    """Resolved desktop root with compatibility accessors for consumers."""

    root: Path

    def required_path(self, name: str) -> Path:
        """Resolve a known desktop resource and fail clearly when absent."""

        relative = {"packageJson": "package.json", "electron": "electron"}.get(
            name, name
        )
        path = self.root / relative
        if not path.exists():
            raise DesktopLayoutMissingError(
                f"desktop resource {name!r} is missing under {self.root}"
            )
        return path


@dataclass(frozen=True)
class DesktopLayoutReceipt:
    """JSON-ready result of validating a repository desktop layout."""

    schema: str
    version: int
    ok: bool
    repo_root: str
    canonical_root: str
    canonical_root_path: str
    selected_manifests: tuple[str, ...]
    scanned_manifests: tuple[str, ...]
    missing_manifests: tuple[str, ...]
    manifest_errors: tuple[str, ...]
    stale_references: tuple[StaleDesktopReference, ...]
    npm_build: UnverifiedProof
    installer: UnverifiedProof
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a structure accepted directly by json.dumps."""

        return {
            "schema": self.schema,
            "version": self.version,
            "ok": self.ok,
            "repo_root": self.repo_root,
            "canonical_root": self.canonical_root,
            "canonical_root_path": self.canonical_root_path,
            "selected_manifests": list(self.selected_manifests),
            "scanned_manifests": list(self.scanned_manifests),
            "missing_manifests": list(self.missing_manifests),
            "manifest_errors": list(self.manifest_errors),
            "stale_references": [
                reference.to_dict() for reference in self.stale_references
            ],
            "proof": {
                "npm_build": self.npm_build.to_dict(),
                "installer": self.installer.to_dict(),
            },
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        """Serialize the receipt deterministically for logs or evidence files."""

        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _repo_root(repo_root: str | Path) -> Path:
    root = Path(repo_root).expanduser().resolve()
    if not root.is_dir():
        raise DesktopLayoutMissingError(f"repository root is not a directory: {root}")
    return root


def locate_desktop_root(repo_root: str | Path) -> Path:
    """Locate the single desktop root under repo_root."""

    root = _repo_root(repo_root)
    candidates = tuple(
        root / relative
        for relative in (CANONICAL_DESKTOP_DIRECTORY, LEGACY_DESKTOP_DIRECTORY)
        if (root / relative).is_dir()
    )
    if len(candidates) == 2:
        raise DesktopLayoutAmbiguousError(
            "ambiguous desktop layout: both desktop and apps/desktop exist"
        )
    if not candidates:
        raise DesktopLayoutMissingError(
            "missing desktop layout: expected desktop or apps/desktop"
        )
    return candidates[0]


def resolve_desktop_layout(repo_root: str | Path) -> DesktopLayout:
    """Return the resolved layout for existing desktop consumers."""

    return DesktopLayout(locate_desktop_root(repo_root))


def _selected_manifest_paths(
    root: Path, manifest_paths: Sequence[str | Path] | None
) -> tuple[tuple[str, Path], ...]:
    selected = (
        DEFAULT_SELECTED_MANIFESTS if manifest_paths is None else tuple(manifest_paths)
    )
    result: list[tuple[str, Path]] = []
    for raw_path in selected:
        value = str(raw_path).replace("\\", "/").strip()
        if not value:
            raise DesktopLayoutContractError(
                "selected manifest paths must be non-empty"
            )
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise DesktopLayoutContractError(
                f"selected manifest path must stay inside repository: {raw_path}"
            )
        relative = candidate.as_posix()
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise DesktopLayoutContractError(
                f"selected manifest path escapes repository: {raw_path}"
            ) from exc
        result.append((relative, resolved))
    return tuple(result)


def build_desktop_layout_receipt(
    repo_root: str | Path,
    *,
    manifest_paths: Sequence[str | Path] | None = None,
) -> DesktopLayoutReceipt:
    """Validate the layout and return a typed, JSON-ready receipt.

    Missing selected files and stale references make receipt.ok false, so
    callers can persist the receipt even when the contract fails. Missing or
    ambiguous desktop roots are structural errors and raise.
    """

    root = _repo_root(repo_root)
    desktop_root = locate_desktop_root(root)
    selected = _selected_manifest_paths(root, manifest_paths)

    scanned: list[str] = []
    missing: list[str] = []
    manifest_errors: list[str] = []
    stale_references: list[StaleDesktopReference] = []
    is_canonical_layout = (
        desktop_root.relative_to(root).as_posix() == CANONICAL_DESKTOP_DIRECTORY
    )

    for relative, path in selected:
        if not path.is_file():
            missing.append(relative)
            continue
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            manifest_errors.append(f"{relative}: cannot read selected manifest ({exc})")
            continue
        scanned.append(relative)
        for line_number, line in enumerate(contents.splitlines(), start=1):
            normalized_line = re.sub(r"/+", "/", line.replace("\\", "/"))
            match = _STALE_DESKTOP_PATTERN.search(normalized_line)
            has_legacy_root = "apps/desktop" in normalized_line.lower()
            if (match is not None or has_legacy_root) and is_canonical_layout:
                stale_references.append(
                    StaleDesktopReference(
                        path=relative,
                        line=line_number,
                        column=match.start() + 1,
                        snippet=line.strip(),
                    )
                )

    npm_build = UnverifiedProof(
        status="unverified",
        reason="npm build was intentionally not run for this contract check",
    )
    installer = UnverifiedProof(
        status="unverified",
        reason="installer proof was intentionally not run for this contract check",
    )
    return DesktopLayoutReceipt(
        schema=DESKTOP_LAYOUT_SCHEMA,
        version=DESKTOP_LAYOUT_VERSION,
        ok=not missing and not manifest_errors and not stale_references,
        repo_root=str(root),
        canonical_root=desktop_root.relative_to(root).as_posix(),
        canonical_root_path=str(desktop_root),
        selected_manifests=tuple(name for name, _ in selected),
        scanned_manifests=tuple(scanned),
        missing_manifests=tuple(missing),
        manifest_errors=tuple(manifest_errors),
        stale_references=tuple(stale_references),
        npm_build=npm_build,
        installer=installer,
        notes=(
            "npm build and installer proof remain unverified",
            "This receipt validates layout and selected-manifest references only",
        ),
    )


find_canonical_desktop_root = locate_desktop_root
validate_desktop_layout = build_desktop_layout_receipt

__all__ = [
    "CANONICAL_DESKTOP_DIRECTORY",
    "DEFAULT_SELECTED_MANIFESTS",
    "DESKTOP_LAYOUT_SCHEMA",
    "DESKTOP_LAYOUT_VERSION",
    "DesktopLayoutAmbiguousError",
    "DesktopLayoutContractError",
    "DesktopLayoutMissingError",
    "DesktopLayout",
    "DesktopLayoutReceipt",
    "LEGACY_DESKTOP_DIRECTORY",
    "STALE_DESKTOP_REFERENCE",
    "StaleDesktopReference",
    "UnverifiedProof",
    "build_desktop_layout_receipt",
    "find_canonical_desktop_root",
    "locate_desktop_root",
    "resolve_desktop_layout",
    "validate_desktop_layout",
]
