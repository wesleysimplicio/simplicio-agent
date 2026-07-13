"""Bounded, deterministic delivery certificates for one task.

This module deliberately proves a local certificate contract only.  It does
not mint a Simplicio Runtime certificate and it does not sign anything.  A
runtime attestation or an external signing key must be supplied by a later
integration; absent those inputs the manifest records ``unavailable`` and
``not_claimed`` explicitly.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping


CERTIFICATE_SCHEMA = "simplicio.delivery-certificate/v1"
LEDGER_SCHEMA = "simplicio.delivery-ledger/v1"
GENESIS_HASH = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERDICTS = frozenset({"passed", "blocked", "unverified"})


class CertificateStatus(str, Enum):
    """Deterministic outcome of certificate evaluation."""

    PASSED = "passed"
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"


class RoutingDecision(str, Enum):
    """Auditable fast/deep routing choice recorded in a manifest."""

    THINK = "think"
    NO_THINK = "no-think"


def sha256_text(value: str) -> str:
    """Return a reproducible SHA-256 digest for UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_is_valid(value: str) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _enum_value(value: str | Enum) -> str:
    return value.value if isinstance(value, Enum) else value


@dataclass(frozen=True)
class EvidenceVerdict:
    """One evidence item and its reported-vs-recomputed verdict.

    Recomputable evidence can satisfy a certificate only when the two verdict
    values are exactly equal.  Missing recomputation therefore remains
    ``unverified`` instead of being treated as a successful claim.
    """

    name: str
    reference: str
    reported: str
    recomputed: str | None = None
    required: bool = True
    recomputable: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("evidence name must be non-empty")
        if not self.reference.strip():
            raise ValueError("evidence reference must be non-empty")
        if self.reported not in _VERDICTS:
            raise ValueError(f"invalid reported evidence verdict: {self.reported!r}")
        if self.recomputed is not None and self.recomputed not in _VERDICTS:
            raise ValueError(
                f"invalid recomputed evidence verdict: {self.recomputed!r}"
            )
        if not self.recomputable and self.recomputed is not None:
            raise ValueError(
                "non-recomputable evidence cannot have a recomputed verdict"
            )

    @property
    def satisfies_requirement(self) -> bool:
        if not self.required or self.reported != CertificateStatus.PASSED.value:
            return not self.required
        if not self.recomputable:
            return True
        return self.recomputed == self.reported

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "reference": self.reference,
            "reported": self.reported,
            "recomputed": self.recomputed,
            "required": self.required,
            "recomputable": self.recomputable,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceVerdict":
        return cls(
            name=str(value["name"]),
            reference=str(value["reference"]),
            reported=str(value["reported"]),
            recomputed=value.get("recomputed"),
            required=bool(value.get("required", True)),
            recomputable=bool(value.get("recomputable", True)),
        )


@dataclass(frozen=True)
class StructuralCheck:
    """A mechanical structural check included in the certificate."""

    name: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("structural check name must be non-empty")
        if not self.detail.strip():
            raise ValueError("structural check detail must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralCheck":
        return cls(
            name=str(value["name"]),
            passed=bool(value["passed"]),
            detail=str(value["detail"]),
        )


@dataclass(frozen=True)
class ReproducibleManifest:
    """Stable inputs needed to identify and replay a task attempt."""

    task_id: str
    agent_version: str
    runtime_version: str | None
    runtime_available: bool
    provider: str
    model: str
    temperature: float | None
    seed: int | None
    prompt_sha256: str
    trajectory_sha256: str
    diff_sha256: str
    routing: RoutingDecision | str
    nondeterminism_reason: str | None = None
    runtime_certificate_claim: bool = False

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("manifest task_id must be non-empty")
        if not self.agent_version.strip():
            raise ValueError("manifest agent_version must be non-empty")
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("manifest provider and model must be non-empty")
        if self.runtime_available and not (self.runtime_version or "").strip():
            raise ValueError("runtime_version is required when runtime is available")
        if self.runtime_certificate_claim:
            raise ValueError(
                "real runtime certificate claims are unavailable in this bounded slice"
            )
        if self.temperature is not None and (
            not math.isfinite(self.temperature) or self.temperature < 0
        ):
            raise ValueError("temperature must be a finite non-negative number")
        if self.seed is not None and not isinstance(self.seed, int):
            raise ValueError("seed must be an integer or None")
        for field_name in ("prompt_sha256", "trajectory_sha256", "diff_sha256"):
            if not _hash_is_valid(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        try:
            RoutingDecision(_enum_value(self.routing))
        except ValueError as exc:
            raise ValueError(f"invalid routing decision: {self.routing!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_version": self.agent_version,
            "runtime_version": self.runtime_version,
            "runtime_available": self.runtime_available,
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "seed": self.seed,
            "prompt_sha256": self.prompt_sha256,
            "trajectory_sha256": self.trajectory_sha256,
            "diff_sha256": self.diff_sha256,
            "routing": _enum_value(self.routing),
            "nondeterminism_reason": self.nondeterminism_reason,
            "runtime_certificate_claim": self.runtime_certificate_claim,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReproducibleManifest":
        return cls(
            task_id=str(value["task_id"]),
            agent_version=str(value["agent_version"]),
            runtime_version=value.get("runtime_version"),
            runtime_available=bool(value["runtime_available"]),
            provider=str(value["provider"]),
            model=str(value["model"]),
            temperature=value.get("temperature"),
            seed=value.get("seed"),
            prompt_sha256=str(value["prompt_sha256"]),
            trajectory_sha256=str(value["trajectory_sha256"]),
            diff_sha256=str(value["diff_sha256"]),
            routing=str(value["routing"]),
            nondeterminism_reason=value.get("nondeterminism_reason"),
            runtime_certificate_claim=bool(
                value.get("runtime_certificate_claim", False)
            ),
        )


@dataclass(frozen=True)
class CertificateVerification:
    """Result of deterministic offline certificate verification."""

    valid: bool
    verdict: CertificateStatus
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TaskCertificate:
    """Typed task delivery certificate with a bounded claim surface."""

    schema: str
    task_id: str
    manifest: ReproducibleManifest
    evidence: tuple[EvidenceVerdict, ...]
    structural_checks: tuple[StructuralCheck, ...]
    status: CertificateStatus | str
    reason: str | None = None
    signing_status: str = "not_claimed"

    def __post_init__(self) -> None:
        if self.schema != CERTIFICATE_SCHEMA:
            raise ValueError(f"unsupported certificate schema: {self.schema!r}")
        if not self.task_id.strip() or self.task_id != self.manifest.task_id:
            raise ValueError(
                "certificate task_id must match a non-empty manifest task_id"
            )
        if _enum_value(self.status) not in {item.value for item in CertificateStatus}:
            raise ValueError(f"invalid certificate status: {self.status!r}")
        if self.signing_status not in {"not_claimed", "unavailable"}:
            raise ValueError(f"invalid signing status: {self.signing_status!r}")
        if (
            _enum_value(self.status) in {"blocked", "unverified"}
            and not (self.reason or "").strip()
        ):
            raise ValueError("blocked and unverified certificates require a reason")

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        manifest: ReproducibleManifest,
        evidence: Iterable[EvidenceVerdict],
        structural_checks: Iterable[StructuralCheck] = (),
        blocked_reason: str | None = None,
        signing_status: str = "not_claimed",
    ) -> "TaskCertificate":
        evidence_items = tuple(evidence)
        checks = tuple(structural_checks)
        reasons = _verification_reasons(manifest, evidence_items, checks)
        if blocked_reason:
            status = CertificateStatus.BLOCKED
            reason = blocked_reason.strip()
        elif reasons:
            status = CertificateStatus.UNVERIFIED
            reason = "; ".join(reasons)
        else:
            status = CertificateStatus.PASSED
            reason = None
        return cls(
            schema=CERTIFICATE_SCHEMA,
            task_id=task_id,
            manifest=manifest,
            evidence=evidence_items,
            structural_checks=checks,
            status=status,
            reason=reason,
            signing_status=signing_status,
        )

    def verify(self) -> CertificateVerification:
        reasons = _verification_reasons(
            self.manifest, self.evidence, self.structural_checks
        )
        expected = (
            CertificateStatus.BLOCKED
            if _enum_value(self.status) == CertificateStatus.BLOCKED.value
            else CertificateStatus.UNVERIFIED
            if reasons
            else CertificateStatus.PASSED
        )
        if (
            _enum_value(self.status) == CertificateStatus.BLOCKED.value
            and not self.reason
        ):
            reasons = ("blocked certificate has no reason",)
        if _enum_value(self.status) != expected.value:
            reasons = (
                *reasons,
                f"declared status is {_enum_value(self.status)!r}, expected {expected.value!r}",
            )
        if _enum_value(self.status) == CertificateStatus.BLOCKED.value and self.reason:
            return CertificateVerification(
                True, CertificateStatus.BLOCKED, (self.reason,)
            )
        return CertificateVerification(not reasons, expected, tuple(reasons))

    @property
    def is_verified(self) -> bool:
        return (
            self.verify().valid
            and _enum_value(self.status) == CertificateStatus.PASSED.value
        )

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize the certificate with stable key ordering."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":") if indent is None else None,
            indent=indent,
        )

    def content_hash(self) -> str:
        return sha256_text(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "manifest": self.manifest.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "structural_checks": [item.to_dict() for item in self.structural_checks],
            "status": _enum_value(self.status),
            "reason": self.reason,
            "signing_status": self.signing_status,
        }

    def __getitem__(self, key: str) -> Any:
        """Keep the previous dictionary-style delivery result read compatible."""

        return self.to_dict()[key]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskCertificate":
        return cls(
            schema=str(value["schema"]),
            task_id=str(value["task_id"]),
            manifest=ReproducibleManifest.from_dict(value["manifest"]),
            evidence=tuple(
                EvidenceVerdict.from_dict(item) for item in value.get("evidence", ())
            ),
            structural_checks=tuple(
                StructuralCheck.from_dict(item)
                for item in value.get("structural_checks", ())
            ),
            status=str(value["status"]),
            reason=value.get("reason"),
            signing_status=str(value.get("signing_status", "not_claimed")),
        )

    @classmethod
    def from_json(cls, text: str) -> "TaskCertificate":
        """Deserialize a certificate without trusting its declared verdict."""

        return cls.from_dict(json.loads(text))


def _verification_reasons(
    manifest: ReproducibleManifest,
    evidence: tuple[EvidenceVerdict, ...],
    structural_checks: tuple[StructuralCheck, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if manifest.runtime_certificate_claim and not manifest.runtime_available:
        reasons.append("runtime certificate claim is unavailable")
    if manifest.runtime_certificate_claim and not structural_checks:
        reasons.append("runtime certificate claim has no structural checks")
    if not evidence:
        reasons.append("required evidence is missing")
    for item in evidence:
        if item.required and not item.reference.strip():
            reasons.append(f"evidence {item.name!r} has no reference")
        if item.required and not item.satisfies_requirement:
            reasons.append(f"evidence {item.name!r} is not deterministically verified")
    if not structural_checks:
        reasons.append("structural checks are missing")
    for check in structural_checks:
        if not check.passed:
            reasons.append(f"structural check {check.name!r} failed")
    return tuple(reasons)


@dataclass(frozen=True)
class LedgerEntry:
    """One hash-linked certificate ledger row."""

    sequence: int
    task_id: str
    certificate_hash: str
    previous_hash: str
    entry_hash: str
    certificate: dict[str, Any]

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA,
            "sequence": self.sequence,
            "task_id": self.task_id,
            "certificate_hash": self.certificate_hash,
            "previous_hash": self.previous_hash,
            "certificate": self.certificate,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "entry_hash": self.entry_hash}


@dataclass(frozen=True)
class LedgerVerification:
    """Offline verification result for a hash-linked ledger."""

    valid: bool
    entries_checked: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "entries_checked": self.entries_checked,
            "reasons": list(self.reasons),
        }


class CertificateLedger:
    """In-memory append-only ledger suitable for durable wrappers."""

    def __init__(self, entries: Iterable[LedgerEntry | Mapping[str, Any]] = ()) -> None:
        self._entries: list[LedgerEntry] = []
        for entry in entries:
            self._entries.append(_coerce_entry(entry))

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def append(self, certificate: TaskCertificate) -> LedgerEntry:
        sequence = len(self._entries)
        previous_hash = self._entries[-1].entry_hash if self._entries else GENESIS_HASH
        unsigned = {
            "schema": LEDGER_SCHEMA,
            "sequence": sequence,
            "task_id": certificate.task_id,
            "certificate_hash": certificate.content_hash(),
            "previous_hash": previous_hash,
            "certificate": certificate.to_dict(),
        }
        entry = LedgerEntry(
            sequence=sequence,
            task_id=certificate.task_id,
            certificate_hash=certificate.content_hash(),
            previous_hash=previous_hash,
            entry_hash=sha256_text(_canonical(unsigned)),
            certificate=certificate.to_dict(),
        )
        self._entries.append(entry)
        return entry

    def verify(self) -> LedgerVerification:
        return verify_ledger(self._entries)

    def to_list(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._entries]


def _coerce_entry(value: LedgerEntry | Mapping[str, Any]) -> LedgerEntry:
    if isinstance(value, LedgerEntry):
        return value
    return LedgerEntry(
        sequence=int(value["sequence"]),
        task_id=str(value["task_id"]),
        certificate_hash=str(value["certificate_hash"]),
        previous_hash=str(value["previous_hash"]),
        entry_hash=str(value["entry_hash"]),
        certificate=dict(value["certificate"]),
    )


def verify_ledger(
    entries: Iterable[LedgerEntry | Mapping[str, Any]],
) -> LedgerVerification:
    """Recompute every row and link; never trusts stored hashes."""

    rows = tuple(_coerce_entry(entry) for entry in entries)
    reasons: list[str] = []
    previous = GENESIS_HASH
    for expected_sequence, entry in enumerate(rows):
        if entry.sequence != expected_sequence:
            reasons.append(f"entry {expected_sequence} has sequence {entry.sequence}")
        if entry.previous_hash != previous:
            reasons.append(f"entry {expected_sequence} has a broken previous-hash link")
        try:
            certificate = TaskCertificate.from_dict(entry.certificate)
            recomputed_certificate_hash = certificate.content_hash()
            if entry.task_id != certificate.task_id:
                reasons.append(
                    f"entry {expected_sequence} task_id does not match certificate"
                )
            if (
                certificate.status == CertificateStatus.PASSED
                and not certificate.is_verified
            ):
                reasons.append(
                    f"entry {expected_sequence} contains an unverified passed certificate"
                )
        except (KeyError, TypeError, ValueError) as exc:
            reasons.append(
                f"entry {expected_sequence} contains an invalid certificate: {exc}"
            )
            recomputed_certificate_hash = ""
        if entry.certificate_hash != recomputed_certificate_hash:
            reasons.append(
                f"entry {expected_sequence} has a mismatched certificate hash"
            )
        unsigned = {
            "schema": LEDGER_SCHEMA,
            "sequence": entry.sequence,
            "task_id": entry.task_id,
            "certificate_hash": entry.certificate_hash,
            "previous_hash": entry.previous_hash,
            "certificate": entry.certificate,
        }
        if entry.entry_hash != sha256_text(_canonical(unsigned)):
            reasons.append(f"entry {expected_sequence} has a mismatched entry hash")
        previous = entry.entry_hash
    return LedgerVerification(not reasons, len(rows), tuple(reasons))


__all__ = [
    "CERTIFICATE_SCHEMA",
    "GENESIS_HASH",
    "LEDGER_SCHEMA",
    "CertificateLedger",
    "CertificateStatus",
    "CertificateVerification",
    "DeliveryCertificate",
    "EvidenceVerdict",
    "LedgerEntry",
    "LedgerVerification",
    "ReproducibleManifest",
    "RoutingDecision",
    "StructuralCheck",
    "TaskCertificate",
    "sha256_text",
    "verify_ledger",
]


# Compatibility name for callers that describe the artifact by its wire role.
DeliveryCertificate = TaskCertificate
