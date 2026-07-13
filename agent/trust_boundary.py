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
    r"(sk-[A-Za-z0-9]{8,}|bearer\s+[A-Za-z0-9._-]+|api[_-]?key|secret)",
    re.IGNORECASE,
)


class TrustBoundaryError(ValueError):
    """Base error for malformed or dishonest trust-boundary data."""


class FailClosedTrustBoundaryError(TrustBoundaryError):
    """Raised when the boundary cannot prove integrity and must deny by default."""


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
        if len(str(self.digest or "").strip()) != 64:
            raise FailClosedTrustBoundaryError("authenticated digest must be 64 hex chars")

    def to_dict(self) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthenticatedDigest":
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
            raise ValueError("provenance source must be non-empty")
        if self.authenticated and self.trust_class in {
            TrustClass.UNTRUSTED_INPUT,
            TrustClass.BLOCKED_COGNITIVE_INTEGRITY,
        }:
            raise ValueError("authenticated provenance cannot be untrusted or blocked")

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
        auth_value = value.get("auth")
        if not isinstance(auth_value, Mapping):
            raise FailClosedTrustBoundaryError("control event requires auth block")
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise FailClosedTrustBoundaryError("control event payload must be an object")
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
        if self.algorithm != DEFAULT_RECEIPT_ALGORITHM:
            raise FailClosedTrustBoundaryError(
                f"unsupported receipt algorithm: {self.algorithm!r}"
            )
        for field_name in ("receipt_id", "subject", "outcome", "issued_at", "digest"):
            if not str(getattr(self, field_name) or "").strip():
                raise FailClosedTrustBoundaryError(
                    f"receipt field {field_name!r} must be non-empty"
                )
        if self.provenance.trust_class is TrustClass.BLOCKED_COGNITIVE_INTEGRITY:
            raise FailClosedTrustBoundaryError("receipts cannot be issued from blocked provenance")

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
                kind=ProvenanceKind(str(provenance.get("kind") or ProvenanceKind.UNKNOWN.value)),
                trust_class=TrustClass(
                    str(provenance.get("trust_class") or TrustClass.UNTRUSTED_INPUT.value)
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
        if self.provenance.trust_class is not TrustClass.BLOCKED_COGNITIVE_INTEGRITY:
            raise ValueError("blocked outcomes require blocked provenance")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "message": self.message,
            "trust_class": self.trust_class.value,
            "provenance": self.provenance.to_dict(),
            "details": _sanitize_mapping(self.details),
        }


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

    control_event = event if isinstance(event, ControlEvent) else ControlEvent.from_dict(event)
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

    integrity_receipt = (
        receipt if isinstance(receipt, IntegrityReceipt) else IntegrityReceipt.from_dict(receipt)
    )
    if previous_receipt and integrity_receipt.previous_digest != previous_receipt.digest:
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


def verify_receipt_chain(receipts: list[IntegrityReceipt | Mapping[str, Any]]) -> TrustProvenance:
    """Verify every receipt and chain link in order."""

    previous: IntegrityReceipt | None = None
    final_provenance: TrustProvenance | None = None
    for item in receipts:
        current = item if isinstance(item, IntegrityReceipt) else IntegrityReceipt.from_dict(item)
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

    return BlockedCognitiveIntegrity(
        reason=reason,
        message=_sanitize_text(message),
        provenance=TrustProvenance(
            kind=ProvenanceKind.UNKNOWN,
            trust_class=TrustClass.BLOCKED_COGNITIVE_INTEGRITY,
            source=source,
            authenticated=False,
        ),
        details=_sanitize_mapping(details or {}),
    )


def enforce_control_event(
    event: ControlEvent | Mapping[str, Any],
    *,
    keyring: Mapping[str, str | bytes],
) -> TrustProvenance | BlockedCognitiveIntegrity:
    """Verify a control event, returning a sanitized blocked result on failure."""

    try:
        return verify_control_event(event, keyring=keyring)
    except TrustBoundaryError as exc:
        return blocked_cognitive_integrity(
            BlockedReason.UNAUTHENTICATED_CONTROL_EVENT,
            message=str(exc),
            details={"event_id": _safe_lookup(event, "event_id"), "auth": _safe_lookup(event, "auth")},
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
    except TrustBoundaryError as exc:
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
        return {str(key): _normalize_value(val) for key, val in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256_hex(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _hmac_digest(secret: str | bytes, value: Any) -> str:
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    return hmac.new(secret_bytes, _canonical_json(value).encode("utf-8"), hashlib.sha256).hexdigest()


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
                _sanitize_text(str(item)) if not isinstance(item, Mapping) else _sanitize_mapping(item)
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
