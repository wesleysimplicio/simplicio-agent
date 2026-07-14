"""Bounded native gateway bridge protocol.

The bridge is deliberately small and transport agnostic.  It is a temporary
compatibility seam: every request carries a lease, and expiry or closure is a
hard boundary after which the handler is never called.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

NATIVE_BRIDGE_SCHEMA = "simplicio.gateway-native/v1"
BRIDGE_LEASE_SCHEMA = "simplicio.gateway-bridge-lease/v1"
BRIDGE_LIFECYCLE_SCHEMA = "simplicio.gateway-lifecycle/v1"
MAX_LEASE_SECONDS = 24 * 60 * 60


class NativeBridgeProtocolError(ValueError):
    """Raised when a request or lease violates the wire contract."""


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NativeBridgeProtocolError("payload must be JSON serializable") from exc


class BridgeLifecyclePhase(str, Enum):
    """Observable phases of the local bridge lifecycle."""

    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"
    ROLLED_BACK = "rolled_back"


class BridgeReceiptStatus(str, Enum):
    """Stable result categories for bridge operations."""

    OK = "ok"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CLOSED = "closed"
    ERROR = "error"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class BridgeLifecycleState:
    """JSON-safe lifecycle snapshot without handler or credential material."""

    bridge_id: str
    phase: BridgeLifecyclePhase
    generation: int
    sequence: int
    expires_at: float
    schema: str = BRIDGE_LIFECYCLE_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.bridge_id, str) or not self.bridge_id:
            raise ValueError("bridge_id must be a non-empty string")
        if not isinstance(self.phase, BridgeLifecyclePhase):
            object.__setattr__(self, "phase", BridgeLifecyclePhase(self.phase))
        for name in ("generation", "sequence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.expires_at, (int, float)) or isinstance(
            self.expires_at, bool
        ):
            raise TypeError("expires_at must be a finite number")
        if not math.isfinite(float(self.expires_at)):
            raise ValueError("expires_at must be a finite number")
        if self.schema != BRIDGE_LIFECYCLE_SCHEMA:
            raise ValueError("unsupported bridge lifecycle schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "bridge_id": self.bridge_id,
            "phase": self.phase.value,
            "generation": self.generation,
            "sequence": self.sequence,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class BridgeReceipt:
    """Typed projection of the existing dictionary receipt interface."""

    status: BridgeReceiptStatus
    ok: bool
    bridge_id: str
    sequence: int
    request_id: str | None = None
    value: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, BridgeReceiptStatus):
            object.__setattr__(self, "status", BridgeReceiptStatus(self.status))
        if not isinstance(self.ok, bool):
            raise TypeError("ok must be a boolean")
        if not isinstance(self.bridge_id, str) or not self.bridge_id:
            raise ValueError("bridge_id must be a non-empty string")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not self.request_id
        ):
            raise ValueError("request_id must be a non-empty string")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": NATIVE_BRIDGE_SCHEMA,
            "status": self.status.value,
            "ok": self.ok,
            "bridge_id": self.bridge_id,
            "sequence": self.sequence,
        }
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.value is not None:
            _json_bytes(self.value)
            result["value"] = self.value
        if self.error:
            result["error"] = self.error
        return result


@dataclass(frozen=True)
class BridgeLease:
    bridge_id: str
    issued_at: float
    expires_at: float
    schema: str = BRIDGE_LEASE_SCHEMA

    @classmethod
    def issue(
        cls,
        ttl_seconds: float,
        *,
        now: float | None = None,
        bridge_id: str | None = None,
    ) -> "BridgeLease":
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise NativeBridgeProtocolError("ttl_seconds must be a finite number")
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or not 0 < ttl <= MAX_LEASE_SECONDS:
            raise NativeBridgeProtocolError(
                "ttl_seconds must be greater than zero and at most 86400"
            )
        if now is not None and (
            isinstance(now, bool) or not isinstance(now, (int, float))
        ):
            raise NativeBridgeProtocolError("now must be a finite number")
        issued = time.time() if now is None else float(now)
        if not math.isfinite(issued):
            raise NativeBridgeProtocolError("now must be a finite number")
        ident = f"bridge-{uuid.uuid4().hex}" if bridge_id is None else bridge_id
        if not ident or not isinstance(ident, str):
            raise NativeBridgeProtocolError("bridge_id must be a non-empty string")
        return cls(ident, issued, issued + ttl)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BridgeLease":
        if not isinstance(value, Mapping):
            raise NativeBridgeProtocolError("lease must be an object")
        for name in ("issued_at", "expires_at"):
            raw_value = value.get(name)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise NativeBridgeProtocolError("lease timestamps must be numbers")
        try:
            lease = cls(
                str(value["bridge_id"]),
                float(value["issued_at"]),
                float(value["expires_at"]),
                str(value.get("schema", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeBridgeProtocolError("invalid bridge lease") from exc
        if (
            lease.schema != BRIDGE_LEASE_SCHEMA
            or not lease.bridge_id
            or not isinstance(value.get("bridge_id"), str)
        ):
            raise NativeBridgeProtocolError("invalid bridge lease schema or bridge_id")
        if not all(
            math.isfinite(value) for value in (lease.issued_at, lease.expires_at)
        ):
            raise NativeBridgeProtocolError("lease timestamps must be finite")
        if lease.expires_at <= lease.issued_at:
            raise NativeBridgeProtocolError("lease expiry must be after issue time")
        if lease.expires_at - lease.issued_at > MAX_LEASE_SECONDS:
            raise NativeBridgeProtocolError("lease exceeds maximum lifetime")
        return lease

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "bridge_id": self.bridge_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def is_expired(self, now: float | None = None) -> bool:
        if now is not None and (
            isinstance(now, bool) or not isinstance(now, (int, float))
        ):
            raise NativeBridgeProtocolError("now must be a finite number")
        observed = time.time() if now is None else float(now)
        if not math.isfinite(observed):
            raise NativeBridgeProtocolError("now must be a finite number")
        return observed >= self.expires_at


@dataclass(frozen=True)
class NativeBridgeRequest:
    request_id: str
    operation: str
    payload: Any
    lease: BridgeLease
    schema: str = NATIVE_BRIDGE_SCHEMA

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NativeBridgeRequest":
        if not isinstance(value, Mapping):
            raise NativeBridgeProtocolError("request must be an object")
        try:
            request = cls(
                value["request_id"],
                value["operation"],
                value.get("payload", {}),
                BridgeLease.from_dict(value["lease"]),
                value.get("schema", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeBridgeProtocolError("invalid native bridge request") from exc
        if (
            request.schema != NATIVE_BRIDGE_SCHEMA
            or not isinstance(request.schema, str)
            or not isinstance(request.request_id, str)
            or not isinstance(request.operation, str)
            or not request.request_id
            or not request.operation
        ):
            raise NativeBridgeProtocolError(
                "invalid request schema, request_id, or operation"
            )
        _json_bytes(request.payload)
        return request

    def to_dict(self) -> dict[str, Any]:
        _json_bytes(self.payload)
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "operation": self.operation,
            "payload": self.payload,
            "lease": self.lease.to_dict(),
        }


class NativeGatewayBridge:
    """Dispatch requests while an isolated, expiring lease remains valid."""

    def __init__(
        self,
        handler: Callable[[str, Any], Any],
        *,
        bridge_id: str = "native-gateway",
        ttl_seconds: float = 300,
        lease: BridgeLease | None = None,
        clock: Callable[[], float] = time.time,
        max_payload_bytes: int = 1024 * 1024,
    ) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        if not isinstance(bridge_id, str) or not bridge_id:
            raise ValueError("bridge_id must be a non-empty string")
        self._handler = handler
        self.bridge_id = bridge_id
        self._clock = clock
        self._lease = (
            BridgeLease.from_dict(lease.to_dict())
            if lease
            else BridgeLease.issue(ttl_seconds, now=clock(), bridge_id=bridge_id)
        )
        if self._lease.bridge_id != bridge_id:
            raise NativeBridgeProtocolError("lease bridge_id does not match bridge")
        if (
            isinstance(max_payload_bytes, bool)
            or not isinstance(max_payload_bytes, int)
            or max_payload_bytes <= 0
        ):
            raise ValueError("max_payload_bytes must be a positive integer")
        self._max_payload_bytes = max_payload_bytes
        self._closed = False
        self._rollback_reason: str | None = None
        self._generation = 0
        self._sequence = 0

    @property
    def lease(self) -> BridgeLease:
        return self._lease

    def close(self) -> dict[str, Any]:
        """Close through the legacy dictionary-returning interface."""
        return self.close_receipt().to_dict()

    def close_receipt(self) -> BridgeReceipt:
        """Close and return the typed receipt projection."""
        self._closed = True
        return BridgeReceipt(
            BridgeReceiptStatus.CLOSED,
            True,
            self.bridge_id,
            self._sequence,
        )

    def rollback(self, reason: str = "rollback_requested") -> dict[str, Any]:
        """Rollback through the legacy dictionary-returning interface."""
        return self.rollback_receipt(reason).to_dict()

    def rollback_receipt(self, reason: str = "rollback_requested") -> BridgeReceipt:
        """Permanently fail closed and return a deterministic rollback receipt.

        The bridge does not own restoration of the legacy handler's state.  A
        caller that detects a failed smoke/health gate uses this marker to
        prevent any further dispatch, then performs restoration in its own
        lifecycle owner.  Repeated rollback is idempotent and retains the
        first causal reason.
        """
        if not isinstance(reason, str) or not reason:
            raise ValueError("rollback reason must be a non-empty string")
        if self._rollback_reason is None:
            self._rollback_reason = reason
            self._generation += 1
        return BridgeReceipt(
            BridgeReceiptStatus.ROLLED_BACK,
            False,
            self.bridge_id,
            self._sequence,
            error=self._rollback_reason,
        )

    def lifecycle(self) -> BridgeLifecycleState:
        """Return the current typed lifecycle snapshot."""
        if self._rollback_reason is not None:
            phase = BridgeLifecyclePhase.ROLLED_BACK
        elif self._closed:
            phase = BridgeLifecyclePhase.CLOSED
        elif self._lease.is_expired(self._clock()):
            phase = BridgeLifecyclePhase.EXPIRED
        else:
            phase = BridgeLifecyclePhase.ACTIVE
        return BridgeLifecycleState(
            bridge_id=self.bridge_id,
            phase=phase,
            generation=self._generation,
            sequence=self._sequence,
            expires_at=self._lease.expires_at,
        )

    def dispatch(self, raw: Mapping[str, Any] | NativeBridgeRequest) -> dict[str, Any]:
        """Dispatch through the legacy dictionary-returning interface."""
        return self.dispatch_receipt(raw).to_dict()

    def dispatch_receipt(
        self, raw: Mapping[str, Any] | NativeBridgeRequest
    ) -> BridgeReceipt:
        """Dispatch and return the typed receipt projection."""
        if self._rollback_reason is not None:
            return BridgeReceipt(
                BridgeReceiptStatus.ROLLED_BACK,
                False,
                self.bridge_id,
                self._sequence,
                error=self._rollback_reason,
            )
        if self._closed:
            return BridgeReceipt(
                BridgeReceiptStatus.CLOSED,
                False,
                self.bridge_id,
                self._sequence,
                error="bridge_closed",
            )
        try:
            request = (
                raw
                if isinstance(raw, NativeBridgeRequest)
                else NativeBridgeRequest.from_dict(raw)
            )
            if request.lease.bridge_id != self.bridge_id:
                return BridgeReceipt(
                    BridgeReceiptStatus.REJECTED,
                    False,
                    self.bridge_id,
                    self._sequence,
                    request_id=request.request_id,
                    error="wrong_bridge_id",
                )
            if request.lease.is_expired(self._clock()):
                return BridgeReceipt(
                    BridgeReceiptStatus.EXPIRED,
                    False,
                    self.bridge_id,
                    self._sequence,
                    request_id=request.request_id,
                    error="lease_expired",
                )
            payload_size = len(_json_bytes(request.payload))
            if payload_size > self._max_payload_bytes:
                return BridgeReceipt(
                    BridgeReceiptStatus.REJECTED,
                    False,
                    self.bridge_id,
                    self._sequence,
                    request_id=request.request_id,
                    error="payload_too_large",
                )
            self._sequence += 1
            value = self._handler(request.operation, request.payload)
            _json_bytes(value)
            return BridgeReceipt(
                BridgeReceiptStatus.OK,
                True,
                self.bridge_id,
                self._sequence,
                request_id=request.request_id,
                value=value,
            )
        except NativeBridgeProtocolError as exc:
            return BridgeReceipt(
                BridgeReceiptStatus.REJECTED,
                False,
                self.bridge_id,
                self._sequence,
                error=str(exc),
            )
        except Exception as exc:
            return BridgeReceipt(
                BridgeReceiptStatus.ERROR,
                False,
                self.bridge_id,
                self._sequence,
                error=type(exc).__name__,
            )

    handle = dispatch

    def health(self) -> dict[str, Any]:
        return {
            "schema": NATIVE_BRIDGE_SCHEMA,
            "bridge_id": self.bridge_id,
            "closed": self._closed,
            "expired": self._lease.is_expired(self._clock()),
            "expires_at": self._lease.expires_at,
            "sequence": self._sequence,
            "lease_digest": hashlib.sha256(
                _json_bytes(self._lease.to_dict())
            ).hexdigest(),
            "lifecycle": self.lifecycle().to_dict(),
        }


__all__ = [
    "BRIDGE_LEASE_SCHEMA",
    "BRIDGE_LIFECYCLE_SCHEMA",
    "MAX_LEASE_SECONDS",
    "NATIVE_BRIDGE_SCHEMA",
    "BridgeLease",
    "BridgeLifecyclePhase",
    "BridgeLifecycleState",
    "BridgeReceipt",
    "BridgeReceiptStatus",
    "NativeBridgeProtocolError",
    "NativeBridgeRequest",
    "NativeGatewayBridge",
]
