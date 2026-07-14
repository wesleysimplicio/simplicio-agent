"""Cognitive-integrity trust boundary helpers.

This module is intentionally small and fail-closed. It models typed
provenance, authenticates control events with deterministic HMAC digests, and
issues tamper-evident receipts that can be chained across steps without
exposing untrusted payloads in blocked outcomes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


COGNITIVE_INTEGRITY_SCHEMA = "simplicio.cognitive-integrity/v1"
DEFAULT_DIGEST_ALGORITHM = "hmac-sha256"
DEFAULT_RECEIPT_ALGORITHM = "sha256"
_SENSITIVE_KEY_RE = re.compile(
    r"(secret|token|password|signature|payload|authorization|cookie|digest|key)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|bearer\s+[A-Za-z0-9._-]+|api[_-]?key|secret)",
    re.IGNORECASE,
)
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class TrustBoundaryError(ValueError):
    """Base error for malformed or dishonest trust-boundary data."""


class FailClosedTrustBoundaryError(TrustBoundaryError):
    """Raised when the boundary cannot prove integrity and must deny by default."""


class ReplayDetectedTrustBoundaryError(FailClosedTrustBoundaryError):
    """Raised when an authenticated control event nonce is reused."""


class TrustClass(str, Enum):
    """Typed trust classes used by the boundary."""

    TRUSTED_CONTROL_PLANE = "trusted_control_plane"
    TRUSTED_RECEIPT = "trusted_receipt"
    UNTRUSTED_INPUT = "untrusted_input"
    BLOCKED_COGNITIVE_INTEGRITY = "blocked_cognitive_integrity"


class ProvenanceKind(str, Enum):
    """Where a datum came from."""

    CONTROL_EVENT = "control_event"
    RECEIPT = "receipt"
    USER_CONTENT = "user_content"
    TOOL_OUTPUT = "tool_output"
    UNKNOWN = "unknown"


class BlockedReason(str, Enum):
    """Fail-closed reasons exposed to callers."""

    UNAUTHENTICATED_CONTROL_EVENT = "unauthenticated_control_event"
    REPLAYED_CONTROL_EVENT = "replayed_control_event"
    TAMPERED_RECEIPT = "tampered_receipt"
    UNTRUSTED_PROVENANCE = "untrusted_provenance"
    MALFORMED_INPUT = "malformed_input"


@dataclass(frozen=True)
class AuthenticatedDigest:
    """Digest metadata for a control event."""

    algorithm: str
    key_id: str
    digest: str

    def __post_init__(self) -> None:
        if self.algorithm != DEFAULT_DIGEST_ALGORITHM:
            raise FailClosedTrustBoundaryError(
                f"unsupported digest algorithm: {self.algorithm!r}"
            )
        if not str(self.key_id or "").strip():
            raise FailClosedTrustBoundaryError("authenticated digest requires key_id")
        if not _HEX_DIGEST_RE.fullmatch(str(self.digest or "").strip()):
            raise FailClosedTrustBoundaryError(
                "authenticated digest must be 64 hex chars"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthenticatedDigest":
        if not isinstance(value, Mapping):
            raise FailClosedTrustBoundaryError("authenticated digest must be an object")
        return cls(
            algorithm=str(value.get("algorithm") or "").strip(),
            key_id=str(value.get("key_id") or "").strip(),
            digest=str(value.get("digest") or "").strip(),
        )


@dataclass(frozen=True)
class TrustProvenance:
    """Typed, serializable provenance for control inputs and receipts."""

    kind: ProvenanceKind
    trust_class: TrustClass
    source: str
    authenticated: bool = False
    key_id: str = ""
    event_id: str = ""
    digest: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if not str(self.source or "").strip():
            raise FailClosedTrustBoundaryError("provenance source must be non-empty")
        if not isinstance(self.kind, ProvenanceKind) or not isinstance(
            self.trust_class, TrustClass
        ):
            raise FailClosedTrustBoundaryError(
                "provenance kind and trust class must be typed"
            )
        if self.trust_class is TrustClass.TRUSTED_CONTROL_PLANE:
            if self.kind is not ProvenanceKind.CONTROL_EVENT or not self.authenticated:
                raise FailClosedTrustBoundaryError(
                    "trusted control provenance is not authenticated"
                )
            if (
                not self.key_id
                or not self.event_id
                or not _HEX_DIGEST_RE.fullmatch(str(self.digest or ""))
            ):
                raise FailClosedTrustBoundaryError(
                    "trusted control provenance is incomplete"
                )
        elif self.trust_class is TrustClass.TRUSTED_RECEIPT:
            if (
                self.kind is not ProvenanceKind.RECEIPT
                or not self.authenticated
                or not _HEX_DIGEST_RE.fullmatch(str(self.digest or ""))
            ):
                raise FailClosedTrustBoundaryError(
                    "trusted receipt provenance is not authenticated"
                )
        elif self.trust_class is TrustClass.UNTRUSTED_INPUT:
            if self.authenticated:
                raise FailClosedTrustBoundaryError(
                    "untrusted provenance cannot be authenticated"
                )
        elif self.trust_class is TrustClass.BLOCKED_COGNITIVE_INTEGRITY:
            if self.authenticated:
                raise FailClosedTrustBoundaryError(
                    "blocked provenance cannot be authenticated"
                )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind.value,
            "trust_class": self.trust_class.value,
            "source": self.source,
            "authenticated": self.authenticated,
        }
        if self.key_id:
            result["key_id"] = self.key_id
        if self.event_id:
            result["event_id"] = self.event_id
        if self.digest:
            result["digest"] = self.digest
        if self.detail:
            result["detail"] = self.detail
        return result


@dataclass(frozen=True)
class ControlEvent:
    """Control-plane event that must authenticate before crossing the boundary."""

    event_id: str
    event_type: str
    actor: str
    issued_at: str
    nonce: str
    payload: Mapping[str, Any]
    auth: AuthenticatedDigest
    schema: str = COGNITIVE_INTEGRITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != COGNITIVE_INTEGRITY_SCHEMA:
            raise FailClosedTrustBoundaryError(
                f"unsupported cognitive-integrity schema: {self.schema!r}"
            )
        if not isinstance(self.payload, Mapping):
            raise FailClosedTrustBoundaryError(
                "control event payload must be an object"
            )
        if not isinstance(self.auth, AuthenticatedDigest):
            raise FailClosedTrustBoundaryError("control event auth must be typed")
        for field_name in ("event_id", "event_type", "actor", "issued_at", "nonce"):
            if not str(getattr(self, field_name) or "").strip():
                raise FailClosedTrustBoundaryError(
                    f"control event field {field_name!r} must be non-empty"
                )

    def signing_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "issued_at": self.issued_at,
            "nonce": self.nonce,
            "payload": _normalize_value(self.payload),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "issued_at": self.issued_at,
            "nonce": self.nonce,
            "payload": _normalize_value(self.payload),
            "auth": self.auth.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ControlEvent":
        if not isinstance(value, Mapping):
            raise FailClosedTrustBoundaryError("control event must be an object")
        auth_value = value.get("auth")
        if not isinstance(auth_value, Mapping):
            raise FailClosedTrustBoundaryError("control event requires auth block")
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise FailClosedTrustBoundaryError(
                "control event payload must be an object"
            )
        return cls(
            schema=str(value.get("schema") or COGNITIVE_INTEGRITY_SCHEMA),
            event_id=str(value.get("event_id") or "").strip(),
            event_type=str(value.get("event_type") or "").strip(),
            actor=str(value.get("actor") or "").strip(),
            issued_at=str(value.get("issued_at") or "").strip(),
            nonce=str(value.get("nonce") or "").strip(),
            payload=payload,
            auth=AuthenticatedDigest.from_dict(auth_value),
        )


@dataclass
class ControlEventReplayGuard:
    """In-memory nonce guard for callers that need replay protection."""

    _seen_nonces: set[str] = field(default_factory=set, repr=False)

    def verify(
        self,
        event: ControlEvent | Mapping[str, Any],
        *,
        keyring: Mapping[str, str | bytes],
    ) -> TrustProvenance:
        """Authenticate an event, then reject and remember each nonce once."""

        control_event = event if isinstance(event, ControlEvent) else ControlEvent.from_dict(event)
        provenance = verify_control_event(control_event, keyring=keyring)
        if control_event.nonce in self._seen_nonces:
            raise ReplayDetectedTrustBoundaryError(
                "control event nonce has already been used"
            )
        self._seen_nonces.add(control_event.nonce)
        return provenance


@dataclass(frozen=True)
class IntegrityReceipt:
    """Tamper-evident receipt with optional chaining to a prior receipt."""

    receipt_id: str
    subject: str
    outcome: str
    issued_at: str
    provenance: TrustProvenance
    body: Mapping[str, Any] = field(default_factory=dict)
    previous_digest: str = ""
    digest: str = ""
    schema: str = COGNITIVE_INTEGRITY_SCHEMA
    algorithm: str = DEFAULT_RECEIPT_ALGORITHM

    def __post_init__(self) -> None:
        if self.schema != COGNITIVE_INTEGRITY_SCHEMA:
            raise FailClosedTrustBoundaryError(
                f"unsupported cognitive-integrity schema: {self.schema!r}"
            )
        if self.algorithm != DEFAULT_RECEIPT_ALGORITHM:
            raise FailClosedTrustBoundaryError(
                f"unsupported receipt algorithm: {self.algorithm!r}"
            )
        for field_name in ("receipt_id", "subject", "outcome", "issued_at", "digest"):
            if not str(getattr(self, field_name) or "").strip():
                raise FailClosedTrustBoundaryError(
                    f"receipt field {field_name!r} must be non-empty"
                )
        if not isinstance(self.provenance, TrustProvenance):
            raise FailClosedTrustBoundaryError("receipt provenance must be typed")
        if not isinstance(self.body, Mapping):
            raise FailClosedTrustBoundaryError("receipt body must be an object")
        if not _HEX_DIGEST_RE.fullmatch(str(self.digest).strip()):
            raise FailClosedTrustBoundaryError("receipt digest must be 64 hex chars")
        if self.previous_digest and not _HEX_DIGEST_RE.fullmatch(self.previous_digest):
            raise FailClosedTrustBoundaryError(
                "receipt previous digest must be 64 hex chars"
            )

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "algorithm": self.algorithm,
            "receipt_id": self.receipt_id,
            "subject": self.subject,
            "outcome": self.outcome,
            "issued_at": self.issued_at,
            "provenance": self.provenance.to_dict(),
            "body": _normalize_value(self.body),
            "previous_digest": self.previous_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.digest_payload(),
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntegrityReceipt":
        if not isinstance(value, Mapping):
            raise FailClosedTrustBoundaryError("receipt must be an object")
        provenance = value.get("provenance")
        body = value.get("body", {})
        if not isinstance(provenance, Mapping):
            raise FailClosedTrustBoundaryError("receipt requires provenance block")
        if not isinstance(body, Mapping):
            raise FailClosedTrustBoundaryError("receipt body must be an object")
        return cls(
            schema=str(value.get("schema") or COGNITIVE_INTEGRITY_SCHEMA),
            algorithm=str(value.get("algorithm") or DEFAULT_RECEIPT_ALGORITHM),
            receipt_id=str(value.get("receipt_id") or "").strip(),
            subject=str(value.get("subject") or "").strip(),
            outcome=str(value.get("outcome") or "").strip(),
            issued_at=str(value.get("issued_at") or "").strip(),
            provenance=TrustProvenance(
                kind=ProvenanceKind(
                    str(provenance.get("kind") or ProvenanceKind.UNKNOWN.value)
                ),
                trust_class=TrustClass(
                    str(
                        provenance.get("trust_class")
                        or TrustClass.UNTRUSTED_INPUT.value
                    )
                ),
                source=str(provenance.get("source") or "").strip(),
                authenticated=bool(provenance.get("authenticated", False)),
                key_id=str(provenance.get("key_id") or "").strip(),
                event_id=str(provenance.get("event_id") or "").strip(),
                digest=str(provenance.get("digest") or "").strip(),
                detail=str(provenance.get("detail") or "").strip(),
            ),
            body=body,
            previous_digest=str(value.get("previous_digest") or "").strip(),
            digest=str(value.get("digest") or "").strip(),
        )


@dataclass(frozen=True)
class BlockedCognitiveIntegrity:
    """Sanitized fail-closed outcome safe to expose to higher layers."""

    reason: BlockedReason
    message: str
    trust_class: TrustClass = TrustClass.BLOCKED_COGNITIVE_INTEGRITY
    provenance: TrustProvenance = field(
        default_factory=lambda: TrustProvenance(
            kind=ProvenanceKind.UNKNOWN,
            trust_class=TrustClass.BLOCKED_COGNITIVE_INTEGRITY,
            source="trust-boundary",
            authenticated=False,
        )
    )
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reason, BlockedReason):
            raise FailClosedTrustBoundaryError(
                "blocked outcomes require a typed reason"
            )
        if self.trust_class is not TrustClass.BLOCKED_COGNITIVE_INTEGRITY:
            raise FailClosedTrustBoundaryError(
                "blocked outcomes require blocked trust class"
            )
        if not isinstance(self.provenance, TrustProvenance):
            raise FailClosedTrustBoundaryError(
                "blocked outcomes require typed provenance"
            )
        if self.provenance.trust_class is not TrustClass.BLOCKED_COGNITIVE_INTEGRITY:
            raise ValueError("blocked outcomes require blocked provenance")
        if not isinstance(self.details, Mapping):
            raise FailClosedTrustBoundaryError(
                "blocked outcome details must be an object"
            )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "message": _sanitize_text(self.message),
            "trust_class": self.trust_class.value,
            "provenance": _sanitize_mapping(self.provenance.to_dict()),
            "details": _sanitize_mapping(self.details),
        }


@dataclass(frozen=True)
class PoisoningQuarantineValidation:
    """Deterministic proof that detected poisoning stayed quarantined."""

    evidence_sha256: str
    poisoning_detected: bool
    quarantined: bool

    def __post_init__(self) -> None:
        if not _HEX_DIGEST_RE.fullmatch(self.evidence_sha256):
            raise FailClosedTrustBoundaryError(
                "poisoning evidence digest must be 64 hex chars"
            )
        if (
            type(self.poisoning_detected) is not bool
            or type(self.quarantined) is not bool
        ):
            raise FailClosedTrustBoundaryError(
                "poisoning and quarantine decisions must be boolean"
            )
        if self.poisoning_detected and not self.quarantined:
            raise FailClosedTrustBoundaryError(
                "detected poisoning must remain quarantined"
            )

    @property
    def safe_to_promote(self) -> bool:
        """Only evidence cleared by both checks may cross the boundary."""

        return not self.poisoning_detected and not self.quarantined


def validate_poisoning_quarantine(
    evidence: Mapping[str, Any],
    *,
    poisoning_detected: bool,
    quarantined: bool,
) -> PoisoningQuarantineValidation:
    """Validate a trusted poisoning decision without retaining raw evidence."""

    if not isinstance(evidence, Mapping) or not evidence:
        raise FailClosedTrustBoundaryError(
            "poisoning validation requires non-empty evidence"
        )
    try:
        evidence_sha256 = _sha256_hex(evidence)
    except (TypeError, ValueError) as exc:
        raise FailClosedTrustBoundaryError(
            "poisoning evidence must be JSON-canonical"
        ) from exc
    return PoisoningQuarantineValidation(
        evidence_sha256=evidence_sha256,
        poisoning_detected=poisoning_detected,
        quarantined=quarantined,
    )


def issue_control_event(
    *,
    event_id: str,
    event_type: str,
    actor: str,
    issued_at: str,
    nonce: str,
    payload: Mapping[str, Any],
    key_id: str,
    secret: str | bytes,
) -> ControlEvent:
    """Construct a signed control event with a canonical HMAC digest."""

    signing_payload = {
        "schema": COGNITIVE_INTEGRITY_SCHEMA,
        "event_id": event_id,
        "event_type": event_type,
        "actor": actor,
        "issued_at": issued_at,
        "nonce": nonce,
        "payload": _normalize_value(payload),
    }
    digest = _hmac_digest(secret, signing_payload)
    return ControlEvent(
        event_id=event_id,
        event_type=event_type,
        actor=actor,
        issued_at=issued_at,
        nonce=nonce,
        payload=payload,
        auth=AuthenticatedDigest(
            algorithm=DEFAULT_DIGEST_ALGORITHM,
            key_id=key_id,
            digest=digest,
        ),
    )


def verify_control_event(
    event: ControlEvent | Mapping[str, Any],
    *,
    keyring: Mapping[str, str | bytes],
) -> TrustProvenance:
    """Verify an authenticated control event or fail closed."""

    if not isinstance(event, (ControlEvent, Mapping)):
        raise FailClosedTrustBoundaryError("control event must be an object")
    if not isinstance(keyring, Mapping):
        raise FailClosedTrustBoundaryError("control-event keyring must be an object")
    control_event = (
        event if isinstance(event, ControlEvent) else ControlEvent.from_dict(event)
    )
    secret = keyring.get(control_event.auth.key_id)
    if secret is None:
        raise FailClosedTrustBoundaryError(
            f"unknown control-event key_id: {control_event.auth.key_id!r}"
        )
    expected = _hmac_digest(secret, control_event.signing_payload())
    if not hmac.compare_digest(expected, control_event.auth.digest):
        raise FailClosedTrustBoundaryError("control event digest verification failed")
    return TrustProvenance(
        kind=ProvenanceKind.CONTROL_EVENT,
        trust_class=TrustClass.TRUSTED_CONTROL_PLANE,
        source=control_event.actor,
        authenticated=True,
        key_id=control_event.auth.key_id,
        event_id=control_event.event_id,
        digest=control_event.auth.digest,
        detail=control_event.event_type,
    )


def issue_receipt(
    *,
    receipt_id: str,
    subject: str,
    outcome: str,
    issued_at: str,
    provenance: TrustProvenance,
    body: Mapping[str, Any] | None = None,
    previous_receipt: IntegrityReceipt | None = None,
) -> IntegrityReceipt:
    """Create a tamper-evident receipt chained to the prior digest when present."""

    if provenance.trust_class not in {
        TrustClass.TRUSTED_CONTROL_PLANE,
        TrustClass.TRUSTED_RECEIPT,
    }:
        raise FailClosedTrustBoundaryError("receipts require trusted provenance")
    previous_digest = previous_receipt.digest if previous_receipt else ""
    receipt_body = dict(body or {})
    payload = {
        "schema": COGNITIVE_INTEGRITY_SCHEMA,
        "algorithm": DEFAULT_RECEIPT_ALGORITHM,
        "receipt_id": receipt_id,
        "subject": subject,
        "outcome": outcome,
        "issued_at": issued_at,
        "provenance": provenance.to_dict(),
        "body": _normalize_value(receipt_body),
        "previous_digest": previous_digest,
    }
    digest = _sha256_hex(payload)
    return IntegrityReceipt(
        receipt_id=receipt_id,
        subject=subject,
        outcome=outcome,
        issued_at=issued_at,
        provenance=provenance,
        body=receipt_body,
        previous_digest=previous_digest,
        digest=digest,
    )


def verify_receipt(
    receipt: IntegrityReceipt | Mapping[str, Any],
    *,
    previous_receipt: IntegrityReceipt | None = None,
) -> TrustProvenance:
    """Verify a receipt digest and optional chain link or fail closed."""

    if not isinstance(receipt, (IntegrityReceipt, Mapping)):
        raise FailClosedTrustBoundaryError("receipt must be an object")
    if previous_receipt is not None and not isinstance(
        previous_receipt, (IntegrityReceipt, Mapping)
    ):
        raise FailClosedTrustBoundaryError("previous receipt must be an object")
    integrity_receipt = (
        receipt
        if isinstance(receipt, IntegrityReceipt)
        else IntegrityReceipt.from_dict(receipt)
    )
    previous = (
        previous_receipt
        if isinstance(previous_receipt, IntegrityReceipt) or previous_receipt is None
        else IntegrityReceipt.from_dict(previous_receipt)
    )
    if previous and integrity_receipt.previous_digest != previous.digest:
        raise FailClosedTrustBoundaryError("receipt chain previous digest mismatch")
    expected = _sha256_hex(integrity_receipt.digest_payload())
    if not hmac.compare_digest(expected, integrity_receipt.digest):
        raise FailClosedTrustBoundaryError("receipt digest verification failed")
    return TrustProvenance(
        kind=ProvenanceKind.RECEIPT,
        trust_class=TrustClass.TRUSTED_RECEIPT,
        source=integrity_receipt.subject,
        authenticated=True,
        digest=integrity_receipt.digest,
        detail=integrity_receipt.outcome,
    )


def verify_receipt_chain(
    receipts: list[IntegrityReceipt | Mapping[str, Any]],
) -> TrustProvenance:
    """Verify every receipt and chain link in order."""

    previous: IntegrityReceipt | None = None
    final_provenance: TrustProvenance | None = None
    for item in receipts:
        current = (
            item
            if isinstance(item, IntegrityReceipt)
            else IntegrityReceipt.from_dict(item)
        )
        final_provenance = verify_receipt(current, previous_receipt=previous)
        previous = current
    if final_provenance is None:
        raise FailClosedTrustBoundaryError("receipt chain cannot be empty")
    return final_provenance


def blocked_cognitive_integrity(
    reason: BlockedReason,
    *,
    message: str,
    details: Mapping[str, Any] | None = None,
    source: str = "trust-boundary",
) -> BlockedCognitiveIntegrity:
    """Build a sanitized blocked outcome safe for higher-layer reporting."""

    if details is not None and not isinstance(details, Mapping):
        raise FailClosedTrustBoundaryError("blocked outcome details must be an object")
    return BlockedCognitiveIntegrity(
        reason=reason,
        message=_sanitize_text(message),
        provenance=TrustProvenance(
            kind=ProvenanceKind.UNKNOWN,
            trust_class=TrustClass.BLOCKED_COGNITIVE_INTEGRITY,
            source=_sanitize_text(source),
            authenticated=False,
        ),
        details=_sanitize_mapping(details or {}),
    )


def enforce_control_event(
    event: ControlEvent | Mapping[str, Any],
    *,
    keyring: Mapping[str, str | bytes],
    replay_guard: ControlEventReplayGuard | None = None,
) -> TrustProvenance | BlockedCognitiveIntegrity:
    """Verify a control event, returning a sanitized blocked result on failure."""

    try:
        if replay_guard is not None:
            return replay_guard.verify(event, keyring=keyring)
        return verify_control_event(event, keyring=keyring)
    except ReplayDetectedTrustBoundaryError:
        return blocked_cognitive_integrity(
            BlockedReason.REPLAYED_CONTROL_EVENT,
            message="control event replay rejected",
            details={"event_id": _safe_lookup(event, "event_id")},
            source="control-event",
        )
    except (TrustBoundaryError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return blocked_cognitive_integrity(
            BlockedReason.UNAUTHENTICATED_CONTROL_EVENT,
            message=str(exc),
            details={
                "event_id": _safe_lookup(event, "event_id"),
                "auth": _safe_lookup(event, "auth"),
            },
            source="control-event",
        )


def enforce_receipt(
    receipt: IntegrityReceipt | Mapping[str, Any],
    *,
    previous_receipt: IntegrityReceipt | None = None,
) -> TrustProvenance | BlockedCognitiveIntegrity:
    """Verify a receipt, returning a sanitized blocked result on failure."""

    try:
        return verify_receipt(receipt, previous_receipt=previous_receipt)
    except (TrustBoundaryError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return blocked_cognitive_integrity(
            BlockedReason.TAMPERED_RECEIPT,
            message=str(exc),
            details={
                "receipt_id": _safe_lookup(receipt, "receipt_id"),
                "subject": _safe_lookup(receipt, "subject"),
                "digest": _safe_lookup(receipt, "digest"),
            },
            source="receipt",
        )


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise FailClosedTrustBoundaryError("canonical objects require string keys")
        return {key: _normalize_value(val) for key, val in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise FailClosedTrustBoundaryError(
                "canonical values cannot contain non-finite numbers"
            )
        return value
    raise FailClosedTrustBoundaryError(
        f"unsupported canonical value type: {type(value).__name__}"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _hmac_digest(secret: str | bytes, value: Any) -> str:
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    return hmac.new(
        secret_bytes, _canonical_json(value).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, raw in value.items():
        clean_key = str(key)
        if _SENSITIVE_KEY_RE.search(clean_key):
            sanitized[clean_key] = "[redacted]"
            continue
        if isinstance(raw, Mapping):
            sanitized[clean_key] = _sanitize_mapping(raw)
            continue
        if isinstance(raw, list):
            sanitized[clean_key] = [
                _sanitize_text(str(item))
                if not isinstance(item, Mapping)
                else _sanitize_mapping(item)
                for item in raw[:5]
            ]
            continue
        sanitized[clean_key] = _sanitize_text(str(raw))
    return sanitized


def _sanitize_text(value: str) -> str:
    clean = " ".join(str(value or "").split())
    clean = _SENSITIVE_VALUE_RE.sub("[redacted]", clean)
    return clean[:240]


def _safe_lookup(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, "")
