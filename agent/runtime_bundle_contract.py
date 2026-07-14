"""Bounded metadata verification for the Simplicio Runtime bundle.

This additive contract verifies caller-supplied identity, version, digest,
health, readiness, and artifact-surface receipts.  It never downloads,
executes, installs, or discovers a runtime.  Missing surfaces stay explicitly
unverified, and a bounded receipt never claims that every official artifact
has been verified.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Final


ISSUE_NUMBER: Final[int] = 127
SCHEMA: Final[str] = "simplicio.runtime-bundle/v1"
MAX_ARTIFACT_SURFACES: Final[int] = 6
MAX_CAPABILITIES: Final[int] = 32
MAX_BLOCKERS: Final[int] = 64
MAX_TEXT_LENGTH: Final[int] = 256
VERIFICATION_SCOPE: Final[str] = (
    "bounded metadata verification of supplied runtime surfaces only; "
    "no claim that every official artifact is verified"
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ArtifactSurface(StrEnum):
    """Release surfaces covered by issue #127's bounded matrix."""

    CLI = "cli"
    PYPI = "pypi"
    BUNDLE = "bundle"
    DOCKER = "docker"
    DESKTOP = "desktop"
    HOMEBREW = "homebrew"


DEFAULT_ARTIFACT_SURFACES: Final[tuple[ArtifactSurface, ...]] = tuple(
    ArtifactSurface
)


class SurfaceEvidenceStatus(StrEnum):
    """Whether a surface receipt is an assertion or verified evidence."""

    VERIFIED = "verified"
    DECLARED = "declared"
    UNAVAILABLE = "unavailable"


class HealthStatus(StrEnum):
    """Health reported by the already-running runtime handshake."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ReadinessStatus(StrEnum):
    """Readiness reported by the already-running runtime handshake."""

    READY = "ready"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    """Aggregate state for the bounded verification receipt."""

    VERIFIED = "verified"
    PARTIAL = "partial"
    BLOCKED = "blocked"


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"{field_name} exceeds {MAX_TEXT_LENGTH} characters")
    return value


def _sha256(value: str, field_name: str) -> str:
    value = _text(value, field_name).lower()
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return value


def sha256_bytes(value: bytes) -> str:
    """Return a SHA-256 digest for caller-owned bytes."""

    if not isinstance(value, bytes):
        raise TypeError("value must be bytes")
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class KernelIdentity:
    """Observed identity returned by the runtime handshake."""

    name: str
    version: str
    commit: str
    protocol_version: str

    def __post_init__(self) -> None:
        for field_name in ("name", "version", "commit", "protocol_version"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))


@dataclass(frozen=True, slots=True)
class RuntimeVersionPin:
    """Expected immutable runtime identity for one compatible bundle."""

    kernel_name: str
    version: str
    commit: str
    protocol_version: str

    def __post_init__(self) -> None:
        for field_name in ("kernel_name", "version", "commit", "protocol_version"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))


@dataclass(frozen=True, slots=True)
class ChecksumEvidence:
    """Expected and observed digest, tied to an external verification receipt."""

    expected_sha256: str
    observed_sha256: str
    receipt: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_sha256", _sha256(self.expected_sha256, "expected_sha256"))
        object.__setattr__(self, "observed_sha256", _sha256(self.observed_sha256, "observed_sha256"))
        object.__setattr__(self, "receipt", _text(self.receipt, "receipt"))

    @property
    def is_verified(self) -> bool:
        return self.expected_sha256 == self.observed_sha256 and bool(self.receipt)


@dataclass(frozen=True, slots=True)
class HealthReadinessEvidence:
    """Bounded health/readiness handshake receipt; no process probing occurs."""

    health: HealthStatus
    readiness: ReadinessStatus
    protocol_version: str
    capabilities: tuple[str, ...] = ()
    receipt: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.health, HealthStatus):
            raise TypeError("health must be a HealthStatus")
        if not isinstance(self.readiness, ReadinessStatus):
            raise TypeError("readiness must be a ReadinessStatus")
        object.__setattr__(self, "protocol_version", _text(self.protocol_version, "protocol_version"))
        if not isinstance(self.capabilities, tuple):
            raise TypeError("capabilities must be a tuple")
        if len(self.capabilities) > MAX_CAPABILITIES:
            raise ValueError(f"capabilities cannot contain more than {MAX_CAPABILITIES} items")
        object.__setattr__(
            self,
            "capabilities",
            tuple(_text(value, "capability") for value in self.capabilities),
        )
        if self.receipt:
            object.__setattr__(self, "receipt", _text(self.receipt, "receipt"))

    @property
    def is_ready(self) -> bool:
        return (
            self.health is HealthStatus.HEALTHY
            and self.readiness is ReadinessStatus.READY
            and bool(self.receipt)
        )


@dataclass(frozen=True, slots=True)
class ArtifactSurfaceEvidence:
    """One explicitly supplied artifact-surface receipt."""

    surface: ArtifactSurface
    version: str
    sha256: str
    receipt: str = ""
    status: SurfaceEvidenceStatus = SurfaceEvidenceStatus.DECLARED

    def __post_init__(self) -> None:
        if not isinstance(self.surface, ArtifactSurface):
            raise TypeError("surface must be an ArtifactSurface")
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        if self.receipt:
            object.__setattr__(self, "receipt", _text(self.receipt, "receipt"))
        if not isinstance(self.status, SurfaceEvidenceStatus):
            raise TypeError("status must be a SurfaceEvidenceStatus")

    def matches(self, pin: RuntimeVersionPin, checksum: ChecksumEvidence) -> bool:
        return (
            self.status is SurfaceEvidenceStatus.VERIFIED
            and bool(self.receipt)
            and self.version == pin.version
            and self.sha256 == checksum.expected_sha256
        )


@dataclass(frozen=True, slots=True)
class VerificationReceipt:
    """Deterministic, fail-closed result of one bounded verification attempt."""

    status: VerificationStatus
    kernel_verified: bool
    version_pin_verified: bool
    checksum_verified: bool
    health_verified: bool
    verified_surfaces: tuple[ArtifactSurface, ...]
    unverified_surfaces: tuple[ArtifactSurface, ...]
    drifted_surfaces: tuple[ArtifactSurface, ...]
    blockers: tuple[str, ...]
    issue_number: int = ISSUE_NUMBER
    scope: str = VERIFICATION_SCOPE

    @property
    def is_verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED

    @property
    def all_artifacts_verified(self) -> bool:
        """Always false: this receipt is bounded and cannot prove every artifact."""

        return False

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["schema"] = SCHEMA
        data["status"] = self.status.value
        for field_name in ("verified_surfaces", "unverified_surfaces", "drifted_surfaces"):
            data[field_name] = [item.value for item in getattr(self, field_name)]
        data["all_artifacts_verified"] = False
        return data

    def to_json(self) -> str:
        """Serialize the receipt deterministically for a caller-owned ledger."""

        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)


@dataclass(frozen=True, slots=True)
class RuntimeBundleContract:
    """Input-only contract for issue #127; it performs no runtime operations."""

    kernel_identity: KernelIdentity | None = None
    version_pin: RuntimeVersionPin | None = None
    checksum: ChecksumEvidence | None = None
    health: HealthReadinessEvidence | None = None
    artifact_surfaces: tuple[ArtifactSurfaceEvidence, ...] = ()
    required_surfaces: tuple[ArtifactSurface, ...] = DEFAULT_ARTIFACT_SURFACES
    issue_number: int = ISSUE_NUMBER

    def __post_init__(self) -> None:
        if self.issue_number != ISSUE_NUMBER:
            raise ValueError(f"issue_number must be {ISSUE_NUMBER}")
        if not isinstance(self.artifact_surfaces, tuple):
            raise TypeError("artifact_surfaces must be a tuple")
        if len(self.artifact_surfaces) > MAX_ARTIFACT_SURFACES:
            raise ValueError(
                f"artifact_surfaces cannot contain more than {MAX_ARTIFACT_SURFACES} items"
            )
        if not all(isinstance(item, ArtifactSurfaceEvidence) for item in self.artifact_surfaces):
            raise TypeError("artifact_surfaces must contain ArtifactSurfaceEvidence instances")
        if not isinstance(self.required_surfaces, tuple):
            raise TypeError("required_surfaces must be a tuple")
        if not self.required_surfaces or len(self.required_surfaces) > MAX_ARTIFACT_SURFACES:
            raise ValueError("required_surfaces must contain between 1 and 6 items")
        if not all(isinstance(item, ArtifactSurface) for item in self.required_surfaces):
            raise TypeError("required_surfaces must contain ArtifactSurface values")
        if len(set(self.required_surfaces)) != len(self.required_surfaces):
            raise ValueError("required_surfaces cannot contain duplicates")

    def verify(self) -> VerificationReceipt:
        """Evaluate supplied metadata and fail closed on any identity drift."""

        blockers: list[str] = []
        kernel_verified = False
        version_pin_verified = False
        checksum_verified = False
        health_verified = False

        identity = self.kernel_identity
        pin = self.version_pin
        checksum = self.checksum
        health = self.health

        if identity is None:
            blockers.append("kernel identity is missing")
        if pin is None:
            blockers.append("version pin is missing")
        if checksum is None:
            blockers.append("checksum evidence is missing")
        if health is None:
            blockers.append("health/readiness evidence is missing")

        if identity is not None and pin is not None:
            identity_fields = (
                ("kernel name", identity.name, pin.kernel_name),
                ("version", identity.version, pin.version),
                ("commit", identity.commit, pin.commit),
                ("protocol version", identity.protocol_version, pin.protocol_version),
            )
            mismatches = [name for name, observed, expected in identity_fields if observed != expected]
            if mismatches:
                blockers.extend(f"kernel drift: {name} does not match version pin" for name in mismatches)
            else:
                kernel_verified = True
                version_pin_verified = True

        if checksum is not None:
            if checksum.is_verified:
                checksum_verified = True
            else:
                blockers.append("checksum drift: observed digest does not match expected digest")

        if health is not None and pin is not None:
            if health.protocol_version != pin.protocol_version:
                blockers.append("health drift: protocol version does not match version pin")
            if not health.is_ready:
                blockers.append("health/readiness is not healthy and ready with a receipt")
            elif health.protocol_version == pin.protocol_version:
                health_verified = True

        by_surface: dict[ArtifactSurface, ArtifactSurfaceEvidence] = {}
        duplicate_surfaces: set[ArtifactSurface] = set()
        for evidence in self.artifact_surfaces:
            if evidence.surface in by_surface:
                duplicate_surfaces.add(evidence.surface)
            by_surface[evidence.surface] = evidence
        for surface in sorted(duplicate_surfaces, key=lambda item: item.value):
            blockers.append(f"artifact surface drift: duplicate evidence for {surface.value}")

        verified_surfaces: list[ArtifactSurface] = []
        unverified_surfaces: list[ArtifactSurface] = []
        drifted_surfaces: list[ArtifactSurface] = []
        for surface in self.required_surfaces:
            evidence = by_surface.get(surface)
            if evidence is None:
                unverified_surfaces.append(surface)
                blockers.append(f"artifact surface unverified: {surface.value} evidence is missing")
                continue
            if not kernel_verified or not checksum_verified or pin is None or checksum is None:
                unverified_surfaces.append(surface)
                continue
            if evidence.matches(pin, checksum):
                verified_surfaces.append(surface)
                continue
            unverified_surfaces.append(surface)
            drifted_surfaces.append(surface)
            blockers.append(f"artifact surface drift: {surface.value} does not match the pin or digest")

        if len(blockers) > MAX_BLOCKERS:
            blockers = blockers[:MAX_BLOCKERS] + ["verification blocker limit exceeded"]

        missing_only = all(
            blocker.startswith("artifact surface unverified:") for blocker in blockers
        )
        if not blockers:
            status = VerificationStatus.VERIFIED
        elif missing_only and verified_surfaces:
            status = VerificationStatus.PARTIAL
        else:
            status = VerificationStatus.BLOCKED

        return VerificationReceipt(
            status=status,
            kernel_verified=kernel_verified,
            version_pin_verified=version_pin_verified,
            checksum_verified=checksum_verified,
            health_verified=health_verified,
            verified_surfaces=tuple(verified_surfaces),
            unverified_surfaces=tuple(unverified_surfaces),
            drifted_surfaces=tuple(drifted_surfaces),
            blockers=tuple(blockers),
            issue_number=self.issue_number,
        )


def verify_runtime_bundle(
    contract: RuntimeBundleContract | None = None, **kwargs: object
) -> VerificationReceipt:
    """Verify a contract, with a small construction convenience."""

    if contract is not None:
        if kwargs:
            raise ValueError("provide either contract or keyword fields, not both")
        return contract.verify()
    return RuntimeBundleContract(**kwargs).verify()


__all__ = [
    "ArtifactSurface",
    "ArtifactSurfaceEvidence",
    "ChecksumEvidence",
    "DEFAULT_ARTIFACT_SURFACES",
    "HealthReadinessEvidence",
    "HealthStatus",
    "ISSUE_NUMBER",
    "KernelIdentity",
    "MAX_ARTIFACT_SURFACES",
    "ReadinessStatus",
    "RuntimeBundleContract",
    "RuntimeVersionPin",
    "SCHEMA",
    "SurfaceEvidenceStatus",
    "VERIFICATION_SCOPE",
    "VerificationReceipt",
    "VerificationStatus",
    "sha256_bytes",
    "verify_runtime_bundle",
]
