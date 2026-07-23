"""Deterministic prompt zones and Runtime inference lease lifecycle.

The stable zone is serialized once from session-frozen inputs. Variable
sections are rendered independently, so conversation state cannot change the
prefix bytes or its digest. Runtime owns slot selection; this module only
keeps the opaque lease token needed to release the session affinity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

__all__ = [
    "InvalidationReason",
    "InferenceLease",
    "LeaseReceipt",
    "PromptZones",
    "RuntimeLeaseTransport",
]


class InvalidationReason(str, Enum):
    """Typed events that invalidate a frozen stable prefix."""

    POLICY = "policy"
    TOOL_REGISTRY = "tool_registry"
    CAPABILITIES = "capabilities"
    MODEL_SWAP = "model_swap"
    CONTEXT_WINDOW = "context_window"


class RuntimeLeaseTransport(Protocol):
    """Small provider-neutral seam implemented by Simplicio Runtime."""

    def acquire(self, session_id: str, prefix_sha256: str, generation: int) -> Mapping[str, Any]: ...

    def release(self, lease_id: str) -> None: ...


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class PromptZones:
    """Own one session's frozen prefix and independently mutable tail."""

    def __init__(
        self,
        stable: Mapping[str, Any],
        variable: Mapping[str, Any] | None = None,
    ) -> None:
        if not stable:
            raise ValueError("stable prompt zone cannot be empty")
        self._stable = dict(stable)
        self._variable = dict(variable or {})
        self._generation = 0
        self._last_invalidation: InvalidationReason | None = None

    @property
    def prefix_bytes(self) -> bytes:
        return _canonical_bytes({"schema": "simplicio.prompt-zones/v1", "stable": self._stable})

    @property
    def prefix_sha256(self) -> str:
        return hashlib.sha256(self.prefix_bytes).hexdigest()

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def variable_tail_bytes(self) -> bytes:
        return _canonical_bytes({"variable": self._variable})

    def invalidate(self, reason: InvalidationReason) -> int:
        if not isinstance(reason, InvalidationReason):
            raise TypeError("reason must be an InvalidationReason")
        self._generation += 1
        self._last_invalidation = reason
        return self._generation

    def set_variable(self, name: str, value: Any) -> None:
        if not name:
            raise ValueError("variable section name cannot be empty")
        self._variable[name] = value

    def receipt(self) -> dict[str, Any]:
        """Return redacted evidence; prompt contents never enter telemetry."""
        return {
            "schema": "simplicio.prompt-zones-receipt/v1",
            "prefix_sha256": self.prefix_sha256,
            "prefix_bytes": len(self.prefix_bytes),
            "generation": self.generation,
            "last_invalidation": (
                self._last_invalidation.value if self._last_invalidation else None
            ),
        }


@dataclass(frozen=True)
class LeaseReceipt:
    """Opaque Runtime lease evidence without slot/provider internals."""

    session_id: str
    lease_id: str
    prefix_sha256: str
    generation: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.inference-lease-receipt/v1",
            "session_id": self.session_id,
            "lease_id": self.lease_id,
            "prefix_sha256": self.prefix_sha256,
            "generation": self.generation,
        }


class InferenceLease:
    """Acquire once per session generation and always release exactly once."""

    def __init__(
        self,
        session_id: str,
        zones: PromptZones,
        transport: RuntimeLeaseTransport,
    ) -> None:
        if not session_id:
            raise ValueError("session_id cannot be empty")
        self._session_id = session_id
        self._zones = zones
        self._transport = transport
        self._receipt: LeaseReceipt | None = None

    @property
    def receipt(self) -> LeaseReceipt | None:
        return self._receipt

    def acquire(self) -> LeaseReceipt:
        current = (self._zones.prefix_sha256, self._zones.generation)
        if self._receipt is not None:
            if (self._receipt.prefix_sha256, self._receipt.generation) == current:
                return self._receipt
            self.finish()
        raw = self._transport.acquire(self._session_id, *current)
        lease_id = raw.get("lease_id")
        if not isinstance(lease_id, str) or not lease_id:
            raise ValueError("Runtime acquire response must contain an opaque lease_id")
        self._receipt = LeaseReceipt(self._session_id, lease_id, *current)
        return self._receipt

    def finish(self) -> None:
        if self._receipt is None:
            return
        receipt, self._receipt = self._receipt, None
        self._transport.release(receipt.lease_id)

    cancel = finish

    def __enter__(self) -> "InferenceLease":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.finish()
