"""Bounded, deterministic delivery certificates for one task.

The certificate is an agent-side contract.  Runtime attestations remain
explicit inputs; this module never upgrades a missing Runtime receipt into a
success.  Ledger rows can be signed with an installation-owned Ed25519 key,
while offline verification recomputes both the hash chain and signatures.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


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


def _private_key(value: Ed25519PrivateKey | bytes) -> Ed25519PrivateKey:
    if isinstance(value, Ed25519PrivateKey):
        return value
    if isinstance(value, bytes):
        try:
            return Ed25519PrivateKey.from_private_bytes(value)
        except ValueError as exc:
            raise ValueError("Ed25519 private key must contain 32 raw bytes") from exc
    raise TypeError("signing_key must be an Ed25519PrivateKey or 32 raw bytes")


def _public_key(value: Ed25519PublicKey | bytes) -> Ed25519PublicKey:
    if isinstance(value, Ed25519PublicKey):
        return value
    if isinstance(value, bytes):
        try:
            return Ed25519PublicKey.from_public_bytes(value)
        except ValueError as exc:
            raise ValueError("Ed25519 public key must contain 32 raw bytes") from exc
    raise TypeError("public_key must be an Ed25519PublicKey or 32 raw bytes")


def _encode_key(value: Ed25519PublicKey) -> str:
    return base64.b64encode(
        value.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def _decode_b64(value: str, label: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"{label} is not valid base64") from exc


@dataclass(frozen=True)
class Ed25519Signer:
    """Process-local signer backed by an installation-owned private key.

    The private key is never serialized into a certificate or ledger row.  A
    caller may persist it outside the repository with :meth:`save` and load it
    again with :meth:`from_file`; the default production path is supplied by
    the caller so tests cannot accidentally write secrets into a checkout.
    """

    signer: str
    private_key: Ed25519PrivateKey

    def __post_init__(self) -> None:
        if not self.signer.strip():
            raise ValueError("signer must be non-empty")

    @property
    def signer_id(self) -> str:
        return self.signer

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self.private_key.public_key()

    def sign(self, payload: bytes) -> str:
        return base64.b64encode(self.private_key.sign(payload)).decode("ascii")

    @classmethod
    def generate(cls, signer: str) -> "Ed25519Signer":
        return cls(signer=signer, private_key=Ed25519PrivateKey.generate())

    @classmethod
    def from_file(cls, path: str | Path, signer: str) -> "Ed25519Signer":
        raw = Path(path).read_bytes()
        if len(raw) != 32:
            raise ValueError("Ed25519 key file must contain exactly 32 raw bytes")
        return cls(signer=signer, private_key=Ed25519PrivateKey.from_private_bytes(raw))

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            self.private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        target.chmod(0o600)


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
class ReplayVerification:
    """Result of comparing a replayed task diff with its manifest."""

    valid: bool
    byte_equal: bool
    explained: bool
    reasons: tuple[str, ...]


def verify_replay(
    manifest: ReproducibleManifest, replayed_diff: str
) -> ReplayVerification:
    """Accept byte-identical replay or an explicit nondeterminism explanation."""

    byte_equal = sha256_text(replayed_diff) == manifest.diff_sha256
    if byte_equal:
        return ReplayVerification(True, True, False, ())
    reason = (manifest.nondeterminism_reason or "").strip()
    if reason:
        return ReplayVerification(True, False, True, (reason,))
    return ReplayVerification(
        False,
        False,
        False,
        (
            "replayed diff is not byte-identical and no nondeterminism reason was recorded",
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
    signature: str | None = None
    public_key: str | None = None
    signer: str | None = None

    @property
    def signer_id(self) -> str | None:
        """Compatibility name for the signer identity in the wire row."""

        return self.signer

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA,
            "sequence": self.sequence,
            "task_id": self.task_id,
            "certificate_hash": self.certificate_hash,
            "previous_hash": self.previous_hash,
            "certificate": self.certificate,
        }

    def signing_dict(self) -> dict[str, Any]:
        """Return the payload covered by an optional Ed25519 signature."""

        payload = self.unsigned_dict()
        if self.public_key is not None:
            payload["public_key"] = self.public_key
        if self.signer is not None:
            payload["signer"] = self.signer
        return payload

    def hash_dict(self) -> dict[str, Any]:
        """Return the payload whose digest becomes the row's entry hash."""

        payload = self.signing_dict()
        if self.signature is not None:
            payload["signature"] = self.signature
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {**self.hash_dict(), "entry_hash": self.entry_hash}


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
    """Append-only ledger with optional per-installation Ed25519 signing.

    The caller owns key generation and storage.  A private key is accepted only
    for the lifetime of this process; the serialized ledger contains the public
    key and signature, never the private key.  Without a key the legacy
    hash-linked ledger remains available but is not a signed ledger.
    """

    def __init__(
        self,
        entries: Iterable[LedgerEntry | Mapping[str, Any]] = (),
        *,
        signing_key: Ed25519PrivateKey | bytes | None = None,
        signer: Ed25519Signer | str | None = None,
        require_signatures: bool = False,
    ) -> None:
        self._entries: list[LedgerEntry] = []
        if isinstance(signer, Ed25519Signer):
            if signing_key is not None:
                raise ValueError("provide either signer or signing_key, not both")
            self._signing_key = signer.private_key
            self._signer = signer.signer_id
        else:
            self._signing_key = (
                _private_key(signing_key) if signing_key is not None else None
            )
            if signer is not None and not signer.strip():
                raise ValueError("signer must be non-empty when provided")
            if signer is not None and self._signing_key is None:
                raise ValueError("signer requires signing_key")
            self._signer = signer
        self._require_signatures = require_signatures
        for entry in entries:
            self._entries.append(_coerce_entry(entry))

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def append(self, certificate: TaskCertificate) -> LedgerEntry:
        sequence = len(self._entries)
        previous_hash = self._entries[-1].entry_hash if self._entries else GENESIS_HASH
        certificate_dict = certificate.to_dict()
        certificate_hash = certificate.content_hash()
        unsigned = {
            "schema": LEDGER_SCHEMA,
            "sequence": sequence,
            "task_id": certificate.task_id,
            "certificate_hash": certificate_hash,
            "previous_hash": previous_hash,
            "certificate": certificate_dict,
        }
        public_key = (
            _encode_key(self._signing_key.public_key())
            if self._signing_key is not None
            else None
        )
        signing_payload = dict(unsigned)
        if public_key is not None:
            signing_payload["public_key"] = public_key
        if self._signer is not None:
            signing_payload["signer"] = self._signer
        signature = (
            base64.b64encode(
                self._signing_key.sign(_canonical(signing_payload).encode("utf-8"))
            ).decode("ascii")
            if self._signing_key is not None
            else None
        )
        hash_payload = dict(signing_payload)
        if signature is not None:
            hash_payload["signature"] = signature
        entry = LedgerEntry(
            sequence=sequence,
            task_id=certificate.task_id,
            certificate_hash=certificate_hash,
            previous_hash=previous_hash,
            entry_hash=sha256_text(_canonical(hash_payload)),
            certificate=certificate_dict,
            signature=signature,
            public_key=public_key,
            signer=self._signer,
        )
        self._entries.append(entry)
        return entry

    def verify(
        self,
        *,
        public_key: Ed25519PublicKey | bytes | None = None,
        require_signatures: bool | None = None,
    ) -> LedgerVerification:
        return verify_ledger(
            self._entries,
            public_key=public_key,
            require_signatures=(
                self._require_signatures
                if require_signatures is None
                else require_signatures
            ),
        )

    def to_list(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._entries]


class SignedLedgerStore:
    """Small JSONL-backed signed ledger store for offline verification."""

    def __init__(
        self,
        path: str | Path,
        signer: Ed25519Signer,
        *,
        require_signatures: bool = True,
    ) -> None:
        if not isinstance(signer, Ed25519Signer):
            raise TypeError("SignedLedgerStore requires an Ed25519Signer")
        self.path = Path(path)
        self.signer = signer
        self.require_signatures = require_signatures

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _write(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            "".join(
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def append(self, certificate: TaskCertificate) -> LedgerEntry:
        rows = self._read()
        if rows:
            existing = verify_ledger(rows, require_signatures=self.require_signatures)
            if not existing.valid:
                raise ValueError(
                    "cannot append to an invalid signed ledger: "
                    + "; ".join(existing.reasons)
                )
        ledger = CertificateLedger(
            rows,
            signer=self.signer,
            require_signatures=self.require_signatures,
        )
        entry = ledger.append(certificate)
        self._write(ledger.to_list())
        return entry

    def verify(self) -> LedgerVerification:
        return verify_ledger_file(self.path, require_signatures=self.require_signatures)

    def to_list(self) -> list[dict[str, Any]]:
        return self._read()


def verify_ledger_file(
    path: str | Path,
    *,
    public_key: Ed25519PublicKey | bytes | None = None,
    require_signatures: bool = True,
) -> LedgerVerification:
    """Verify a JSONL ledger without requiring its private signing key."""

    ledger_path = Path(path)
    try:
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            ledger_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"line {line_number} is not an object")
                rows.append(value)
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return LedgerVerification(False, len(rows), (f"invalid ledger file: {exc}",))
    return verify_ledger(
        rows,
        public_key=public_key,
        require_signatures=require_signatures,
    )


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
        signature=value.get("signature"),
        public_key=value.get("public_key"),
        signer=value.get("signer"),
    )


def verify_ledger(
    entries: Iterable[LedgerEntry | Mapping[str, Any]],
    *,
    public_key: Ed25519PublicKey | bytes | None = None,
    require_signatures: bool = False,
) -> LedgerVerification:
    """Recompute every row, link, and available Ed25519 signature offline."""

    rows = tuple(_coerce_entry(entry) for entry in entries)
    reasons: list[str] = []
    previous = GENESIS_HASH
    expected_public_key: Ed25519PublicKey | None = None
    if public_key is not None:
        try:
            expected_public_key = _public_key(public_key)
        except (TypeError, ValueError) as exc:
            reasons.append(f"provided public key is invalid: {exc}")
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
        if entry.entry_hash != sha256_text(_canonical(entry.hash_dict())):
            reasons.append(f"entry {expected_sequence} has a mismatched entry hash")
        if require_signatures and entry.signature is None:
            reasons.append(f"entry {expected_sequence} is unsigned")
        if entry.signature is not None:
            if entry.public_key is None:
                reasons.append(f"entry {expected_sequence} has no public key")
            else:
                try:
                    embedded_public_key = _public_key(
                        _decode_b64(entry.public_key, "public key")
                    )
                    if (
                        expected_public_key is not None
                        and embedded_public_key.public_bytes(
                            serialization.Encoding.Raw,
                            serialization.PublicFormat.Raw,
                        )
                        != expected_public_key.public_bytes(
                            serialization.Encoding.Raw,
                            serialization.PublicFormat.Raw,
                        )
                    ):
                        reasons.append(
                            f"entry {expected_sequence} uses an unexpected public key"
                        )
                    embedded_public_key.verify(
                        _decode_b64(entry.signature, "signature"),
                        _canonical(entry.signing_dict()).encode("utf-8"),
                    )
                except (InvalidSignature, TypeError, ValueError) as exc:
                    reasons.append(
                        f"entry {expected_sequence} has an invalid signature: {exc}"
                    )
        elif entry.public_key is not None:
            reasons.append(
                f"entry {expected_sequence} has a public key but no signature"
            )
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
    "Ed25519Signer",
    "EvidenceVerdict",
    "LedgerEntry",
    "LedgerVerification",
    "ReproducibleManifest",
    "ReplayVerification",
    "RoutingDecision",
    "SignedLedgerStore",
    "StructuralCheck",
    "TaskCertificate",
    "sha256_text",
    "verify_ledger_file",
    "verify_replay",
    "verify_ledger",
]


# Compatibility name for callers that describe the artifact by its wire role.
DeliveryCertificate = TaskCertificate
