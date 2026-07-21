"""Foundational, evidence-gated Asolaria integration contracts.

This module deliberately stops at typed, deterministic contracts.  It does
not claim that HRM is embedded, that a watcher process is running, or that a
Brown-Hilbert label proves a physical property.  Runtime execution and any
external benchmark must provide their own receipt before a result can become
``VERIFIED``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Final


ISSUE_NUMBER: Final[int] = 17
SCHEMA: Final[str] = "simplicio.asolaria-integration/v1"
HRM_SCHEMA: Final[str] = "hrm-controller/v1"
N_NEST_SCHEMA: Final[str] = "n-nest/v1"
MAX_TEXT_LENGTH: Final[int] = 2_048
MAX_ITEMS: Final[int] = 32
MAX_DEPTH: Final[int] = 64
_REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_ADDRESS_RE = re.compile(r"^R(?:\.(?:0|[1-9][0-9]*))*$")
_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class AsolariaIntegrationError(ValueError):
    """Base error raised when an integration contract fails closed."""


class UnverifiablePhysicsClaim(AsolariaIntegrationError):
    """Raised when a physical claim lacks independently verified evidence."""


class EvidenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    BLOCKED = "BLOCKED"


class ClaimKind(StrEnum):
    BEHAVIORAL = "behavioral"
    PERFORMANCE = "performance"
    PHYSICS = "physics"


def _text(value: Any, name: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise AsolariaIntegrationError(f"{name} must be a bounded non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AsolariaIntegrationError(f"{name} contains control characters")
    return value


def _token(value: Any, name: str) -> str:
    value = _text(value, name)
    if any(char.isspace() for char in value):
        raise AsolariaIntegrationError(f"{name} must be a single token")
    return value


def _texts(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise AsolariaIntegrationError(f"{name} must be a sequence of strings")
    if len(value) > MAX_ITEMS:
        raise AsolariaIntegrationError(f"{name} exceeds {MAX_ITEMS} items")
    return tuple(_text(item, f"{name}[{index}]") for index, item in enumerate(value))


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _status(value: Any, name: str = "status") -> EvidenceStatus:
    try:
        return value if isinstance(value, EvidenceStatus) else EvidenceStatus(value)
    except (TypeError, ValueError) as exc:
        raise AsolariaIntegrationError(
            f"{name} must be VERIFIED, UNVERIFIED, or BLOCKED"
        ) from exc


@dataclass(frozen=True, slots=True)
class NestAddress:
    """Canonical tree address; the label is not a mathematical proof."""

    segments: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.segments, tuple):
            try:
                object.__setattr__(self, "segments", tuple(self.segments))
            except TypeError as exc:
                raise AsolariaIntegrationError(
                    "address segments must be iterable"
                ) from exc
        if len(self.segments) > MAX_DEPTH:
            raise AsolariaIntegrationError(f"address depth exceeds {MAX_DEPTH}")
        for index, segment in enumerate(self.segments):
            if isinstance(segment, bool) or not isinstance(segment, int) or segment < 0:
                raise AsolariaIntegrationError(
                    f"address segment {index} must be a non-negative integer"
                )

    @classmethod
    def parse(cls, value: str) -> "NestAddress":
        if not isinstance(value, str) or not _ADDRESS_RE.fullmatch(value):
            raise AsolariaIntegrationError(
                "address must use canonical R or R.<non-negative-integer> path syntax"
            )
        parts = value.split(".")[1:]
        return cls(tuple(int(part) for part in parts))

    @property
    def path(self) -> str:
        return "R" + "".join(f".{segment}" for segment in self.segments)

    @property
    def depth(self) -> int:
        return len(self.segments)

    @property
    def parent(self) -> "NestAddress | None":
        return None if not self.segments else NestAddress(self.segments[:-1])

    def child(self, segment: int) -> "NestAddress":
        if isinstance(segment, bool) or not isinstance(segment, int) or segment < 0:
            raise AsolariaIntegrationError(
                "child segment must be a non-negative integer"
            )
        return NestAddress(self.segments + (segment,))


@dataclass(frozen=True, slots=True)
class GenerativeIdentity:
    """Deterministic identity derived from namespace and address.

    ``seed_bytes`` is exactly eight bytes.  It is a derived value, not a
    claim about storage capacity, entropy, consciousness, or physics.
    """

    namespace: str
    address: NestAddress

    def __post_init__(self) -> None:
        _token(self.namespace, "identity.namespace")
        if not isinstance(self.address, NestAddress):
            raise TypeError("identity.address must be a NestAddress")

    @property
    def seed_bytes(self) -> bytes:
        material = _canonical({
            "namespace": self.namespace,
            "address": self.address.path,
        }).encode("utf-8")
        return hashlib.sha256(material).digest()[:8]

    @property
    def seed_hex(self) -> str:
        return self.seed_bytes.hex()

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.seed_bytes).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "address": self.address.path,
            "seed_hex": self.seed_hex,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class AsolariaProvenance:
    """Pinned source and execution evidence for an integration claim."""

    source: str
    repository: str
    url: str
    revision: str
    evidence: tuple[str, ...]
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    runtime_receipt: str | None = None

    def __post_init__(self) -> None:
        _token(self.source, "provenance.source")
        _text(self.repository, "provenance.repository")
        _text(self.url, "provenance.url")
        if not isinstance(self.revision, str) or not _REVISION_RE.fullmatch(
            self.revision
        ):
            raise AsolariaIntegrationError(
                "provenance.revision must be an immutable git revision"
            )
        object.__setattr__(
            self, "evidence", _texts(self.evidence, "provenance.evidence")
        )
        object.__setattr__(self, "status", _status(self.status, "provenance.status"))
        if self.runtime_receipt is not None:
            _text(self.runtime_receipt, "provenance.runtime_receipt")
        if self.status is EvidenceStatus.VERIFIED and not self.evidence:
            raise AsolariaIntegrationError(
                "verified provenance requires at least one evidence reference"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "repository": self.repository,
            "url": self.url,
            "revision": self.revision,
            "evidence": list(self.evidence),
            "status": self.status.value,
            "runtime_receipt": self.runtime_receipt,
        }


@dataclass(frozen=True, slots=True)
class IntegrationClaim:
    """A bounded claim with an explicit falsifier and evidence status."""

    statement: str
    kind: ClaimKind
    falsifier: str
    evidence: tuple[str, ...] = ()
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED

    def __post_init__(self) -> None:
        _text(self.statement, "claim.statement")
        try:
            kind = (
                self.kind if isinstance(self.kind, ClaimKind) else ClaimKind(self.kind)
            )
        except (TypeError, ValueError) as exc:
            raise AsolariaIntegrationError("claim.kind is not supported") from exc
        object.__setattr__(self, "kind", kind)
        _text(self.falsifier, "claim.falsifier")
        object.__setattr__(self, "evidence", _texts(self.evidence, "claim.evidence"))
        object.__setattr__(self, "status", _status(self.status, "claim.status"))
        if kind is ClaimKind.PHYSICS and self.status is not EvidenceStatus.VERIFIED:
            raise UnverifiablePhysicsClaim(
                "physics claims require VERIFIED evidence; the contract does not infer physics"
            )
        if self.status is EvidenceStatus.VERIFIED and not self.evidence:
            raise AsolariaIntegrationError(
                "verified claims require at least one evidence reference"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "kind": self.kind.value,
            "falsifier": self.falsifier,
            "evidence": list(self.evidence),
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class CorrectiveGateReceipt:
    """Watcher-style comparison receipt without spawning a process."""

    address: NestAddress
    reported_digest: str
    recomputed_digest: str
    provenance: AsolariaProvenance
    status: EvidenceStatus

    def __post_init__(self) -> None:
        if not isinstance(self.address, NestAddress):
            raise TypeError("gate.address must be a NestAddress")
        for name in ("reported_digest", "recomputed_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
                raise AsolariaIntegrationError(f"gate.{name} must be a SHA-256 digest")
        if not isinstance(self.provenance, AsolariaProvenance):
            raise TypeError("gate.provenance must be AsolariaProvenance")
        object.__setattr__(self, "status", _status(self.status, "gate.status"))

    @property
    def accepted(self) -> bool:
        return self.status is EvidenceStatus.VERIFIED

    @classmethod
    def evaluate(
        cls,
        address: NestAddress,
        reported: object,
        recomputed: object,
        provenance: AsolariaProvenance,
    ) -> "CorrectiveGateReceipt":
        if not isinstance(address, NestAddress):
            raise TypeError("gate.address must be a NestAddress")
        if not isinstance(provenance, AsolariaProvenance):
            raise TypeError("gate.provenance must be AsolariaProvenance")
        reported_digest = _digest(reported)
        recomputed_digest = _digest(recomputed)
        status = (
            EvidenceStatus.BLOCKED
            if reported_digest != recomputed_digest
            else provenance.status
        )
        return cls(address, reported_digest, recomputed_digest, provenance, status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address.path,
            "reported_digest": self.reported_digest,
            "recomputed_digest": self.recomputed_digest,
            "provenance": self.provenance.to_dict(),
            "status": self.status.value,
            "accepted": self.accepted,
        }


@dataclass(frozen=True, slots=True)
class AsolariaIntegrationManifest:
    """Typed link between the existing HRM controller and N-Nest address."""

    address: NestAddress
    identity: GenerativeIdentity
    provenance: AsolariaProvenance
    claims: tuple[IntegrationClaim, ...] = ()
    hrm_schema: str = HRM_SCHEMA
    nest_schema: str = N_NEST_SCHEMA
    boundary: str = "contract-only: no runtime execution, process watcher, benchmark, or physics claim"
    schema: str = SCHEMA
    issue_number: int = ISSUE_NUMBER

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise AsolariaIntegrationError(f"schema must equal {SCHEMA!r}")
        if self.issue_number != ISSUE_NUMBER:
            raise AsolariaIntegrationError(f"issue_number must be {ISSUE_NUMBER}")
        if not isinstance(self.address, NestAddress):
            raise TypeError("manifest.address must be a NestAddress")
        if not isinstance(self.identity, GenerativeIdentity):
            raise TypeError("manifest.identity must be GenerativeIdentity")
        if self.identity.address != self.address:
            raise AsolariaIntegrationError(
                "identity.address must match manifest.address"
            )
        if not isinstance(self.provenance, AsolariaProvenance):
            raise TypeError("manifest.provenance must be AsolariaProvenance")
        if self.hrm_schema != HRM_SCHEMA or self.nest_schema != N_NEST_SCHEMA:
            raise AsolariaIntegrationError(
                "manifest must bind the supported HRM and N-Nest schemas"
            )
        if not isinstance(self.claims, Sequence) or isinstance(
            self.claims, (str, bytes)
        ):
            raise AsolariaIntegrationError("manifest.claims must be a sequence")
        if len(self.claims) > MAX_ITEMS or any(
            not isinstance(claim, IntegrationClaim) for claim in self.claims
        ):
            raise AsolariaIntegrationError("manifest.claims contains an invalid claim")
        object.__setattr__(self, "claims", tuple(self.claims))
        _text(self.boundary, "manifest.boundary")

    @property
    def status(self) -> EvidenceStatus:
        if self.provenance.status is not EvidenceStatus.VERIFIED:
            return EvidenceStatus.UNVERIFIED
        if any(claim.status is not EvidenceStatus.VERIFIED for claim in self.claims):
            return EvidenceStatus.UNVERIFIED
        return EvidenceStatus.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "issue_number": self.issue_number,
            "hrm_schema": self.hrm_schema,
            "nest_schema": self.nest_schema,
            "address": self.address.path,
            "identity": self.identity.to_dict(),
            "provenance": self.provenance.to_dict(),
            "claims": [claim.to_dict() for claim in self.claims],
            "boundary": self.boundary,
            "status": self.status.value,
        }

    def to_json(self) -> str:
        return _canonical(self.to_dict())


__all__ = [
    "AsolariaIntegrationError",
    "AsolariaIntegrationManifest",
    "AsolariaProvenance",
    "ClaimKind",
    "CorrectiveGateReceipt",
    "EvidenceStatus",
    "GenerativeIdentity",
    "HRM_SCHEMA",
    "IntegrationClaim",
    "ISSUE_NUMBER",
    "N_NEST_SCHEMA",
    "NestAddress",
    "SCHEMA",
    "UnverifiablePhysicsClaim",
]
