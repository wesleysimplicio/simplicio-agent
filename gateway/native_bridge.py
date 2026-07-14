"""Bounded native gateway bridge protocol.

The bridge is deliberately small and transport agnostic.  It is a temporary
compatibility seam: every request carries a lease, and expiry or closure is a
hard boundary after which the handler is never called.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

NATIVE_BRIDGE_SCHEMA = "simplicio.gateway-native/v1"
BRIDGE_LEASE_SCHEMA = "simplicio.gateway-bridge-lease/v1"
MAX_LEASE_SECONDS = 24 * 60 * 60


class NativeBridgeProtocolError(ValueError):
    """Raised when a request or lease violates the wire contract."""


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    except (TypeError, ValueError) as exc:
        raise NativeBridgeProtocolError("payload must be JSON serializable") from exc


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
        ttl = float(ttl_seconds)
        if not 0 < ttl <= MAX_LEASE_SECONDS:
            raise NativeBridgeProtocolError(
                "ttl_seconds must be greater than zero and at most 86400"
            )
        issued = time.time() if now is None else float(now)
        ident = bridge_id or f"bridge-{uuid.uuid4().hex}"
        if not ident or not isinstance(ident, str):
            raise NativeBridgeProtocolError("bridge_id must be a non-empty string")
        return cls(ident, issued, issued + ttl)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BridgeLease":
        if not isinstance(value, Mapping):
            raise NativeBridgeProtocolError("lease must be an object")
        try:
            lease = cls(
                str(value["bridge_id"]),
                float(value["issued_at"]),
                float(value["expires_at"]),
                str(value.get("schema", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeBridgeProtocolError("invalid bridge lease") from exc
        if lease.schema != BRIDGE_LEASE_SCHEMA or not lease.bridge_id:
            raise NativeBridgeProtocolError("invalid bridge lease schema or bridge_id")
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
        return (time.time() if now is None else float(now)) >= self.expires_at


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
                str(value["request_id"]),
                str(value["operation"]),
                value.get("payload", {}),
                BridgeLease.from_dict(value["lease"]),
                str(value.get("schema", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise NativeBridgeProtocolError("invalid native bridge request") from exc
        if (
            request.schema != NATIVE_BRIDGE_SCHEMA
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
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        self._max_payload_bytes = max_payload_bytes
        self._closed = False
        self._sequence = 0

    @property
    def lease(self) -> BridgeLease:
        return self._lease

    def close(self) -> dict[str, Any]:
        self._closed = True
        return self._receipt("closed", ok=True)

    def _receipt(
        self,
        status: str,
        *,
        ok: bool,
        request_id: str | None = None,
        value: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": NATIVE_BRIDGE_SCHEMA,
            "status": status,
            "ok": ok,
            "bridge_id": self.bridge_id,
            "sequence": self._sequence,
        }
        if request_id is not None:
            result["request_id"] = request_id
        if value is not None:
            _json_bytes(value)
            result["value"] = value
        if error:
            result["error"] = error
        return result

    def dispatch(self, raw: Mapping[str, Any] | NativeBridgeRequest) -> dict[str, Any]:
        if self._closed:
            return self._receipt("closed", ok=False, error="bridge_closed")
        try:
            request = (
                raw
                if isinstance(raw, NativeBridgeRequest)
                else NativeBridgeRequest.from_dict(raw)
            )
            if request.lease.bridge_id != self.bridge_id:
                return self._receipt(
                    "rejected",
                    ok=False,
                    request_id=request.request_id,
                    error="wrong_bridge_id",
                )
            if request.lease.is_expired(self._clock()):
                return self._receipt(
                    "expired",
                    ok=False,
                    request_id=request.request_id,
                    error="lease_expired",
                )
            payload_size = len(_json_bytes(request.payload))
            if payload_size > self._max_payload_bytes:
                return self._receipt(
                    "rejected",
                    ok=False,
                    request_id=request.request_id,
                    error="payload_too_large",
                )
            self._sequence += 1
            value = self._handler(request.operation, request.payload)
            _json_bytes(value)
            return self._receipt(
                "ok", ok=True, request_id=request.request_id, value=value
            )
        except NativeBridgeProtocolError as exc:
            return self._receipt("rejected", ok=False, error=str(exc))
        except Exception as exc:
            return self._receipt("error", ok=False, error=type(exc).__name__)

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
        }


__all__ = [
    "BRIDGE_LEASE_SCHEMA",
    "MAX_LEASE_SECONDS",
    "NATIVE_BRIDGE_SCHEMA",
    "BridgeLease",
    "NativeBridgeProtocolError",
    "NativeBridgeRequest",
    "NativeGatewayBridge",
]
