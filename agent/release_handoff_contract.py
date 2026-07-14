"""Bounded release-handoff audit contract for issue #144.

This module records the evidence that a release handoff still needs.  It is
deliberately additive: it does not run installers, inspect a machine, or wire
itself into a runtime surface.  A complete evidence record therefore remains
blocked until the separate clean-machine release gate is satisfied.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Final, Iterable


ISSUE_NUMBER: Final = 144
REQUIRED_LIFECYCLE_OPERATIONS: Final = (
    "install",
    "update",
    "rollback",
    "uninstall",
)
DEFAULT_RUNTIME_SURFACES: Final = (
    "desktop",
    "apps/desktop",
    "agent",
    "runtime",
    "cli",
    "mcp",
)
DEFAULT_OFF_INTEGRATIONS: Final = ("google", "stripe")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class EvidenceStatus(str, Enum):
    """State of a receipt-backed item in the handoff audit."""

    VERIFIED = "verified"
    MISSING = "missing"
    BLOCKED = "blocked"


class ReadinessStatus(str, Enum):
    """Release readiness is intentionally only exposed as an explicit block."""

    BLOCKED = "blocked"


@dataclass(frozen=True)
class ArtifactEvidence:
    """An artifact receipt; the receipt must identify a reproducible artifact."""

    path: str
    receipt: str | None = None

    @property
    def is_verified(self) -> bool:
        return bool(self.path.strip() and (self.receipt or "").strip())


@dataclass(frozen=True)
class ChecksumEvidence:
    """A SHA-256 receipt tied to one named artifact."""

    artifact: str
    sha256: str | None = None
    receipt: str | None = None

    @property
    def is_verified(self) -> bool:
        return bool(
            self.artifact.strip()
            and self.sha256
            and _SHA256_RE.fullmatch(self.sha256.strip())
            and (self.receipt or "").strip()
        )


@dataclass(frozen=True)
class LifecycleEvidence:
    """Receipt for one lifecycle operation."""

    receipt: str | None = None
    status: EvidenceStatus = EvidenceStatus.MISSING
    notes: str | None = None

    @property
    def is_verified(self) -> bool:
        return self.status is EvidenceStatus.VERIFIED and bool(
            (self.receipt or "").strip()
        )


@dataclass(frozen=True)
class RuntimeSurfaceEvidence:
    """Receipt that a named runtime surface was exercised or inspected."""

    name: str
    receipt: str | None = None
    status: EvidenceStatus = EvidenceStatus.MISSING

    @property
    def is_verified(self) -> bool:
        return bool(self.name.strip()) and self.status is EvidenceStatus.VERIFIED and bool(
            (self.receipt or "").strip()
        )


@dataclass(frozen=True)
class DefaultOffIntegrationEvidence:
    """Evidence that an integration remains disabled by default."""

    name: str
    enabled: bool = False
    receipt: str | None = None
    status: EvidenceStatus = EvidenceStatus.MISSING

    @property
    def is_verified(self) -> bool:
        return (
            bool(self.name.strip())
            and not self.enabled
            and self.status is EvidenceStatus.VERIFIED
            and bool((self.receipt or "").strip())
        )


@dataclass(frozen=True)
class ReleaseHandoffAudit:
    """Machine-readable audit output with an honest readiness boundary."""

    issue_number: int
    readiness: ReadinessStatus
    evidence_complete: bool
    verified_checks: tuple[str, ...]
    blockers: tuple[str, ...]
    clean_machine_release_proof: str = "not_proven"

    @property
    def is_blocked(self) -> bool:
        return self.readiness is ReadinessStatus.BLOCKED

    @property
    def is_ready(self) -> bool:
        """Never claim release readiness from this bounded audit alone."""

        return False

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe handoff receipt."""

        data = asdict(self)
        data["readiness"] = self.readiness.value
        return data

    def to_json(self) -> str:
        """Serialize the receipt deterministically for handoff storage."""

        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


@dataclass(frozen=True)
class ReleaseHandoffContract:
    """Input contract for issue #144's bounded release audit.

    The defaults identify the required categories, but intentionally contain no
    fabricated evidence.  Callers provide receipts from their own release
    steps; this class only evaluates their shape and completeness.
    """

    artifacts: tuple[ArtifactEvidence, ...] = ()
    checksums: tuple[ChecksumEvidence, ...] = ()
    install: LifecycleEvidence = LifecycleEvidence()
    update: LifecycleEvidence = LifecycleEvidence()
    rollback: LifecycleEvidence = LifecycleEvidence()
    uninstall: LifecycleEvidence = LifecycleEvidence()
    runtime_surfaces: tuple[RuntimeSurfaceEvidence, ...] = ()
    default_off_integrations: tuple[DefaultOffIntegrationEvidence, ...] = ()
    required_runtime_surfaces: tuple[str, ...] = DEFAULT_RUNTIME_SURFACES
    required_default_off_integrations: tuple[str, ...] = DEFAULT_OFF_INTEGRATIONS
    issue_number: int = ISSUE_NUMBER

    def audit(self) -> ReleaseHandoffAudit:
        """Evaluate evidence without performing any release operation."""

        blockers: list[str] = []
        verified: list[str] = []

        self._audit_artifacts(blockers, verified)
        self._audit_checksums(blockers, verified)
        self._audit_lifecycle(blockers, verified)
        self._audit_runtime_surfaces(blockers, verified)
        self._audit_default_off_integrations(blockers, verified)

        evidence_complete = not blockers
        # This is a permanent blocker for this bounded contract.  A later
        # clean-machine release gate may consume this receipt, but this module
        # must never turn handoff evidence into a release-readiness claim.
        blockers.append(
            "readiness blocked: clean-machine release proof is outside the bounded "
            f"issue #{self.issue_number} audit contract"
        )
        return ReleaseHandoffAudit(
            issue_number=self.issue_number,
            readiness=ReadinessStatus.BLOCKED,
            evidence_complete=evidence_complete,
            verified_checks=tuple(verified),
            blockers=tuple(blockers),
        )

    def _audit_artifacts(self, blockers: list[str], verified: list[str]) -> None:
        if not self.artifacts:
            blockers.append("artifacts: no artifact evidence supplied")
            return
        for artifact in self.artifacts:
            if artifact.is_verified:
                verified.append(f"artifact:{artifact.path.strip()}")
            else:
                label = artifact.path.strip() or "<unnamed>"
                blockers.append(f"artifacts: missing receipt for {label}")

    def _audit_checksums(self, blockers: list[str], verified: list[str]) -> None:
        if not self.checksums:
            blockers.append("checksums: no SHA-256 evidence supplied")
            return

        artifact_names = {
            artifact.path.strip() for artifact in self.artifacts if artifact.path.strip()
        }
        seen: set[str] = set()
        for checksum in self.checksums:
            artifact_name = checksum.artifact.strip()
            if not artifact_name or artifact_name not in artifact_names:
                blockers.append(
                    "checksums: entry is not tied to a required artifact "
                    f"({artifact_name or '<unnamed>'})"
                )
                continue
            seen.add(artifact_name)
            if not checksum.sha256 or not _SHA256_RE.fullmatch(checksum.sha256.strip()):
                blockers.append(f"checksums: invalid SHA-256 for {artifact_name}")
            elif not (checksum.receipt or "").strip():
                blockers.append(f"checksums: missing receipt for {artifact_name}")
            else:
                verified.append(f"checksum:{artifact_name}")

        for artifact_name in sorted(artifact_names - seen):
            blockers.append(f"checksums: missing checksum for {artifact_name}")

    def _audit_lifecycle(self, blockers: list[str], verified: list[str]) -> None:
        evidence = {
            "install": self.install,
            "update": self.update,
            "rollback": self.rollback,
            "uninstall": self.uninstall,
        }
        for operation in REQUIRED_LIFECYCLE_OPERATIONS:
            item = evidence[operation]
            if item.is_verified:
                verified.append(operation)
            else:
                blockers.append(f"{operation}: verified receipt is missing")

    def _audit_runtime_surfaces(self, blockers: list[str], verified: list[str]) -> None:
        evidence = {surface.name.strip(): surface for surface in self.runtime_surfaces}
        for name in self.required_runtime_surfaces:
            normalized = name.strip()
            item = evidence.get(normalized)
            if item is None:
                blockers.append(f"runtime surface: missing evidence for {normalized}")
            elif item.is_verified:
                verified.append(f"runtime:{normalized}")
            else:
                blockers.append(f"runtime surface: unverified evidence for {normalized}")

    def _audit_default_off_integrations(
        self, blockers: list[str], verified: list[str]
    ) -> None:
        evidence = {
            integration.name.strip(): integration
            for integration in self.default_off_integrations
        }
        for name in self.required_default_off_integrations:
            normalized = name.strip()
            item = evidence.get(normalized)
            if item is None:
                blockers.append(f"default-off integration: missing evidence for {normalized}")
            elif item.enabled:
                blockers.append(f"default-off integration: {normalized} is enabled")
            elif item.is_verified:
                verified.append(f"default-off:{normalized}")
            else:
                blockers.append(
                    f"default-off integration: unverified evidence for {normalized}"
                )


def audit_release_handoff(
    contract: ReleaseHandoffContract | None = None,
    *,
    artifacts: Iterable[ArtifactEvidence] = (),
    checksums: Iterable[ChecksumEvidence] = (),
    install: LifecycleEvidence | None = None,
    update: LifecycleEvidence | None = None,
    rollback: LifecycleEvidence | None = None,
    uninstall: LifecycleEvidence | None = None,
    runtime_surfaces: Iterable[RuntimeSurfaceEvidence] = (),
    default_off_integrations: Iterable[DefaultOffIntegrationEvidence] = (),
) -> ReleaseHandoffAudit:
    """Audit a contract, with a small keyword-only construction convenience."""

    if contract is not None:
        if any(
            (
                tuple(artifacts),
                tuple(checksums),
                install,
                update,
                rollback,
                uninstall,
                tuple(runtime_surfaces),
                tuple(default_off_integrations),
            )
        ):
            raise ValueError("provide either contract or evidence keyword arguments, not both")
        return contract.audit()

    return ReleaseHandoffContract(
        artifacts=tuple(artifacts),
        checksums=tuple(checksums),
        install=install or LifecycleEvidence(),
        update=update or LifecycleEvidence(),
        rollback=rollback or LifecycleEvidence(),
        uninstall=uninstall or LifecycleEvidence(),
        runtime_surfaces=tuple(runtime_surfaces),
        default_off_integrations=tuple(default_off_integrations),
    ).audit()


__all__ = [
    "ArtifactEvidence",
    "ChecksumEvidence",
    "DEFAULT_OFF_INTEGRATIONS",
    "DEFAULT_RUNTIME_SURFACES",
    "DefaultOffIntegrationEvidence",
    "EvidenceStatus",
    "ISSUE_NUMBER",
    "LifecycleEvidence",
    "ReadinessStatus",
    "ReleaseHandoffAudit",
    "ReleaseHandoffContract",
    "REQUIRED_LIFECYCLE_OPERATIONS",
    "RuntimeSurfaceEvidence",
    "audit_release_handoff",
]
