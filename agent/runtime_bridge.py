"""Narrow Agent/Runtime bridge ownership contract for issue #159."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from tools.runtime_handshake import ProtocolRange


RUNTIME_BRIDGE_SCHEMA = "simplicio.runtime-bridge/v1"


@dataclass(frozen=True, slots=True)
class RuntimeBridgeContract:
    """Machine-readable ownership and compatibility boundary."""

    agent_protocol: ProtocolRange
    runtime_protocol: ProtocolRange
    transport: str
    runtime_owner: str = "simplicio-runtime"
    gate_owner: str = "simplicio-runtime"
    required_schemas: tuple[str, ...] = ()
    mutations_require_gate: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.agent_protocol, ProtocolRange) or not isinstance(
            self.runtime_protocol, ProtocolRange
        ):
            raise TypeError("protocols must be ProtocolRange values")
        if not str(self.transport).strip():
            raise ValueError("transport must be non-empty")
        object.__setattr__(self, "transport", str(self.transport).strip())
        schemas = tuple(sorted({str(item).strip() for item in self.required_schemas}))
        if any(not item for item in schemas):
            raise ValueError("required_schemas must contain non-empty values")
        object.__setattr__(self, "required_schemas", schemas)
        if not isinstance(self.mutations_require_gate, bool):
            raise TypeError("mutations_require_gate must be boolean")

    @property
    def compatible(self) -> bool:
        return self.agent_protocol.overlaps(self.runtime_protocol)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RUNTIME_BRIDGE_SCHEMA,
            "agent_protocol": self.agent_protocol.to_dict(),
            "runtime_protocol": self.runtime_protocol.to_dict(),
            "transport": self.transport,
            "runtime_owner": self.runtime_owner,
            "gate_owner": self.gate_owner,
            "required_schemas": list(self.required_schemas),
            "mutations_require_gate": self.mutations_require_gate,
            "compatible": self.compatible,
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["RUNTIME_BRIDGE_SCHEMA", "RuntimeBridgeContract"]
