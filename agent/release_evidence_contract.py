"""Bounded, additive Desktop CI/release evidence contract for issue #130.

This module evaluates receipt metadata only.  It never invokes a build,
installer, signing tool, or subprocess, and a verified receipt is not a claim
that this module built an installer.  Callers provide evidence from their CI
or release system; missing, malformed, duplicate, or orphaned evidence is
always rejected.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Final


ISSUE_NUMBER: Final = 130
CONTRACT_SCHEMA: Final = "simplicio.desktop-release-evidence"
CONTRACT_VERSION: Final = f"{CONTRACT_SCHEMA}/v1"
MAX_EVIDENCE_ITEMS: Final = 128
MAX_BLOCKERS: Final = 64

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


class EvidenceStatus(str, Enum):
    """Receipt state for evidence that must be supplied by a caller."""

    VERIFIED = "verified"
    MISSING = "missing"
    BLOCKED = "blocked"


class MatrixOutcome(str, Enum):
    """Outcome of one declared CI matrix cell."""

    PASS = "pass"
    FAIL = "fail"
    MISSING = "missing"


class ReproducibilityStatus(str, Enum):
    """Status of an independently recorded reproducibility comparison."""

    VERIFIED = "verified"
    NOT_PROVEN = "not_proven"
    MISMATCH = "mismatch"


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _bounded(value: object) -> bool:
    return isinstance(value, (tuple, list)) and len(value) <= MAX_EVIDENCE_ITEMS


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Stable identity for one release artifact, independent of its path."""

    artifact_id: str
    product: str
    version: str
    platform: str
    architecture: str
    format: str

    def blockers(self, prefix: str = "artifact") -> list[str]:
        errors: list[str] = []
        for name, value in (
            ("id", self.artifact_id),
            ("product", self.product),
            ("version", self.version),
            ("platform", self.platform),
            ("architecture", self.architecture),
            ("format", self.format),
        ):
            if not _text(value):
                errors.append(f"{prefix}: {name} must be a non-empty string")
        return errors


@dataclass(frozen=True, slots=True)
class BuildInputs:
    """Immutable inputs needed to reproduce a release build elsewhere."""

    source_commit: str
    lockfile_sha256: str
    toolchain: str
    configuration: str
    receipt: str | None = None

    def blockers(self) -> list[str]:
        errors: list[str] = []
        if not _text(self.source_commit) or not _COMMIT_RE.fullmatch(self.source_commit.strip()):
            errors.append("build inputs: source_commit must be an immutable git SHA")
        if not _text(self.lockfile_sha256) or not _SHA256_RE.fullmatch(self.lockfile_sha256.strip()):
            errors.append("build inputs: lockfile_sha256 must be a valid SHA-256")
        if not _text(self.toolchain):
            errors.append("build inputs: toolchain must be a non-empty string")
        if not _text(self.configuration):
            errors.append("build inputs: configuration must be a non-empty string")
        if not _text(self.receipt):
            errors.append("build inputs: receipt is missing")
        return errors


@dataclass(frozen=True, slots=True)
class InstallerEvidence:
    """Receipt metadata for an installer artifact; no build is performed here."""

    artifact_id: str
    receipt: str | None = None
    status: EvidenceStatus = EvidenceStatus.MISSING

    @property
    def is_verified(self) -> bool:
        return (
            _text(self.artifact_id)
            and self.status is EvidenceStatus.VERIFIED
            and _text(self.receipt)
        )


@dataclass(frozen=True, slots=True)
class ChecksumEvidence:
    """SHA-256 receipt tied to one declared artifact identity."""

    artifact_id: str
    sha256: str | None = None
    receipt: str | None = None

    @property
    def is_verified(self) -> bool:
        return (
            _text(self.artifact_id)
            and _text(self.sha256)
            and _SHA256_RE.fullmatch(self.sha256.strip()) is not None
            and _text(self.receipt)
        )


@dataclass(frozen=True, slots=True)
class SignatureEvidence:
    """Receipt for signature verification without storing signature material."""

    artifact_id: str
    key_id: str
    signature_format: str
    receipt: str | None = None
    status: EvidenceStatus = EvidenceStatus.MISSING

    @property
    def is_verified(self) -> bool:
        return (
            _text(self.artifact_id)
            and _text(self.key_id)
            and _text(self.signature_format)
            and self.status is EvidenceStatus.VERIFIED
            and _text(self.receipt)
        )


@dataclass(frozen=True, slots=True)
class MatrixResult:
    """Receipt-backed result for one named Desktop CI matrix cell."""

    name: str
    platform: str
    architecture: str
    outcome: MatrixOutcome = MatrixOutcome.MISSING
    receipt: str | None = None

    @property
    def is_verified(self) -> bool:
        return (
            _text(self.name)
            and _text(self.platform)
            and _text(self.architecture)
            and self.outcome is MatrixOutcome.PASS
            and _text(self.receipt)
        )


@dataclass(frozen=True, slots=True)
class ReproducibilityEvidence:
    """Explicit comparison result; ``VERIFIED`` still requires a receipt."""

    status: ReproducibilityStatus = ReproducibilityStatus.NOT_PROVEN
    comparison_receipt: str | None = None

    @property
    def is_verified(self) -> bool:
        return self.status is ReproducibilityStatus.VERIFIED and _text(self.comparison_receipt)


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceAudit:
    """Deterministic result of the evidence gate, not a build assertion."""

    issue_number: int
    schema_version: str
    evidence_complete: bool
    reproducibility_status: ReproducibilityStatus
    verified_checks: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)

    @property
    def is_ready(self) -> bool:
        """Return evidence-gate readiness only; never release/build readiness."""

        return self.evidence_complete and not self.blockers

    @property
    def readiness(self) -> str:
        """Expose the evidence-only readiness label used in serialized receipts."""

        return "evidence_complete" if self.is_ready else "blocked"

    @property
    def installer_build_claimed(self) -> bool:
        """This bounded contract deliberately never claims an installer build."""

        return False

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["reproducibility_status"] = self.reproducibility_status.value
        data["readiness"] = self.readiness
        data["installer_build_claimed"] = self.installer_build_claimed
        return data

    def to_json(self) -> str:
        """Serialize this receipt with stable key ordering."""

        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceContract:
    """Bounded input contract for Desktop CI/release evidence."""

    artifacts: tuple[ArtifactIdentity, ...] = ()
    build_inputs: BuildInputs | None = None
    installers: tuple[InstallerEvidence, ...] = ()
    checksums: tuple[ChecksumEvidence, ...] = ()
    signatures: tuple[SignatureEvidence, ...] = ()
    required_matrix: tuple[str, ...] = ()
    matrix_results: tuple[MatrixResult, ...] = ()
    reproducibility: ReproducibilityEvidence = ReproducibilityEvidence()
    issue_number: int = ISSUE_NUMBER

    def audit(self) -> ReleaseEvidenceAudit:
        """Evaluate supplied metadata without performing release operations."""

        blockers: list[str] = []
        verified: list[str] = []

        artifact_ids = self._audit_artifacts(blockers, verified)
        self._audit_build_inputs(blockers, verified)
        self._audit_installers(artifact_ids, blockers, verified)
        self._audit_checksums(artifact_ids, blockers, verified)
        self._audit_signatures(artifact_ids, blockers, verified)
        self._audit_matrix(blockers, verified)
        reproducibility_status = self._audit_reproducibility(blockers, verified)

        if not isinstance(self.issue_number, int) or isinstance(self.issue_number, bool):
            blockers.append("issue number: must be a positive integer")

        return ReleaseEvidenceAudit(
            issue_number=self.issue_number if isinstance(self.issue_number, int) else ISSUE_NUMBER,
            schema_version=CONTRACT_VERSION,
            evidence_complete=not blockers,
            reproducibility_status=reproducibility_status,
            verified_checks=tuple(verified),
            blockers=tuple(blockers[:MAX_BLOCKERS]),
        )

    def _audit_artifacts(self, blockers: list[str], verified: list[str]) -> set[str]:
        if not _bounded(self.artifacts) or not self.artifacts:
            blockers.append("artifacts: a non-empty bounded artifact list is required")
            return set()
        ids: set[str] = set()
        for artifact in self.artifacts:
            if not isinstance(artifact, ArtifactIdentity):
                blockers.append("artifacts: entry has an invalid type")
                continue
            errors = artifact.blockers()
            artifact_id = artifact.artifact_id.strip() if _text(artifact.artifact_id) else "<unnamed>"
            if artifact_id in ids:
                errors.append(f"artifacts: duplicate artifact identity {artifact_id}")
            else:
                ids.add(artifact_id)
            blockers.extend(errors)
            if not errors:
                verified.append(f"artifact:{artifact_id}")
        return ids

    def _audit_build_inputs(self, blockers: list[str], verified: list[str]) -> None:
        if self.build_inputs is None:
            blockers.append("build inputs: evidence is missing")
            return
        if not isinstance(self.build_inputs, BuildInputs):
            blockers.append("build inputs: invalid evidence type")
            return
        errors = self.build_inputs.blockers()
        blockers.extend(errors)
        if not errors:
            verified.append("build-inputs")

    def _audit_installers(self, artifact_ids: set[str], blockers: list[str], verified: list[str]) -> None:
        if not _bounded(self.installers) or not self.installers:
            blockers.append("installers: receipt evidence is missing")
            return
        seen: set[str] = set()
        for item in self.installers:
            if not isinstance(item, InstallerEvidence):
                blockers.append("installers: entry has an invalid type")
                continue
            artifact_id = item.artifact_id.strip() if _text(item.artifact_id) else "<unnamed>"
            if artifact_id not in artifact_ids:
                blockers.append(f"installers: orphan evidence for {artifact_id}")
            if artifact_id in seen:
                blockers.append(f"installers: duplicate evidence for {artifact_id}")
            seen.add(artifact_id)
            if not item.is_verified:
                blockers.append(f"installers: verified receipt is missing for {artifact_id}")
            elif artifact_id in artifact_ids:
                verified.append(f"installer:{artifact_id}")
        for artifact_id in sorted(artifact_ids - seen):
            blockers.append(f"installers: missing evidence for {artifact_id}")

    def _audit_checksums(self, artifact_ids: set[str], blockers: list[str], verified: list[str]) -> None:
        if not _bounded(self.checksums) or not self.checksums:
            blockers.append("checksums: SHA-256 evidence is missing")
            return
        seen: set[str] = set()
        for item in self.checksums:
            if not isinstance(item, ChecksumEvidence):
                blockers.append("checksums: entry has an invalid type")
                continue
            artifact_id = item.artifact_id.strip() if _text(item.artifact_id) else "<unnamed>"
            if artifact_id not in artifact_ids:
                blockers.append(f"checksums: orphan evidence for {artifact_id}")
            if artifact_id in seen:
                blockers.append(f"checksums: duplicate evidence for {artifact_id}")
            seen.add(artifact_id)
            if not item.is_verified:
                blockers.append(f"checksums: valid SHA-256 receipt is missing for {artifact_id}")
            elif artifact_id in artifact_ids:
                verified.append(f"checksum:{artifact_id}")
        for artifact_id in sorted(artifact_ids - seen):
            blockers.append(f"checksums: missing evidence for {artifact_id}")

    def _audit_signatures(self, artifact_ids: set[str], blockers: list[str], verified: list[str]) -> None:
        if not _bounded(self.signatures) or not self.signatures:
            blockers.append("signatures: verification evidence is missing")
            return
        seen: set[str] = set()
        for item in self.signatures:
            if not isinstance(item, SignatureEvidence):
                blockers.append("signatures: entry has an invalid type")
                continue
            artifact_id = item.artifact_id.strip() if _text(item.artifact_id) else "<unnamed>"
            if artifact_id not in artifact_ids:
                blockers.append(f"signatures: orphan evidence for {artifact_id}")
            if artifact_id in seen:
                blockers.append(f"signatures: duplicate evidence for {artifact_id}")
            seen.add(artifact_id)
            if not item.is_verified:
                blockers.append(f"signatures: verified receipt is missing for {artifact_id}")
            elif artifact_id in artifact_ids:
                verified.append(f"signature:{artifact_id}")
        for artifact_id in sorted(artifact_ids - seen):
            blockers.append(f"signatures: missing evidence for {artifact_id}")

    def _audit_matrix(self, blockers: list[str], verified: list[str]) -> None:
        if not _bounded(self.required_matrix) or not self.required_matrix:
            blockers.append("matrix: a non-empty bounded required matrix is missing")
            return
        required = [name.strip() for name in self.required_matrix if _text(name)]
        if len(required) != len(self.required_matrix):
            blockers.append("matrix: every required cell must have a non-empty name")
        if len(set(required)) != len(required):
            blockers.append("matrix: duplicate required cell name")
        if not _bounded(self.matrix_results) or not self.matrix_results:
            blockers.append("matrix: results are missing")
            return
        results: dict[str, MatrixResult] = {}
        for item in self.matrix_results:
            if not isinstance(item, MatrixResult):
                blockers.append("matrix: result has an invalid type")
                continue
            name = item.name.strip() if _text(item.name) else "<unnamed>"
            if name in results:
                blockers.append(f"matrix: duplicate result for {name}")
            results[name] = item
            if name not in required:
                blockers.append(f"matrix: unexpected result for {name}")
            if not item.is_verified:
                blockers.append(f"matrix: passing receipt is missing for {name}")
            else:
                verified.append(f"matrix:{name}")
        for name in required:
            if name not in results:
                blockers.append(f"matrix: missing result for {name}")

    def _audit_reproducibility(self, blockers: list[str], verified: list[str]) -> ReproducibilityStatus:
        if not isinstance(self.reproducibility, ReproducibilityEvidence):
            blockers.append("reproducibility: evidence is missing")
            return ReproducibilityStatus.NOT_PROVEN
        status = self.reproducibility.status
        if not isinstance(status, ReproducibilityStatus):
            blockers.append("reproducibility: status is invalid")
            return ReproducibilityStatus.NOT_PROVEN
        if status is ReproducibilityStatus.VERIFIED and self.reproducibility.is_verified:
            verified.append("reproducibility")
        else:
            blockers.append(f"reproducibility: verified status and comparison receipt are required ({status.value})")
        return status


def audit_release_evidence(
    contract: ReleaseEvidenceContract | None = None,
    *,
    artifacts: Iterable[ArtifactIdentity] = (),
    build_inputs: BuildInputs | None = None,
    installers: Iterable[InstallerEvidence] = (),
    checksums: Iterable[ChecksumEvidence] = (),
    signatures: Iterable[SignatureEvidence] = (),
    required_matrix: Iterable[str] = (),
    matrix_results: Iterable[MatrixResult] = (),
    reproducibility: ReproducibilityEvidence | None = None,
) -> ReleaseEvidenceAudit:
    """Audit a contract or construct one from keyword-only evidence."""

    if contract is not None:
        if any((tuple(artifacts), build_inputs, tuple(installers), tuple(checksums), tuple(signatures), tuple(required_matrix), tuple(matrix_results), reproducibility)):
            raise ValueError("provide either contract or evidence keyword arguments, not both")
        return contract.audit()
    return ReleaseEvidenceContract(
        artifacts=tuple(artifacts),
        build_inputs=build_inputs,
        installers=tuple(installers),
        checksums=tuple(checksums),
        signatures=tuple(signatures),
        required_matrix=tuple(required_matrix),
        matrix_results=tuple(matrix_results),
        reproducibility=reproducibility or ReproducibilityEvidence(),
    ).audit()


__all__ = [
    "ArtifactIdentity",
    "BuildInputs",
    "CONTRACT_SCHEMA",
    "CONTRACT_VERSION",
    "ChecksumEvidence",
    "EvidenceStatus",
    "InstallerEvidence",
    "ISSUE_NUMBER",
    "MAX_BLOCKERS",
    "MAX_EVIDENCE_ITEMS",
    "MatrixOutcome",
    "MatrixResult",
    "ReproducibilityEvidence",
    "ReproducibilityStatus",
    "ReleaseEvidenceAudit",
    "ReleaseEvidenceContract",
    "SignatureEvidence",
    "audit_release_evidence",
]
