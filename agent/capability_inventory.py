"""Verifiable capability inventory records for Universal Operator discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


CAPABILITY_INVENTORY_SCHEMA = "simplicio.capability-inventory/v1"


class CapabilityDisposition(StrEnum):
    ADOPT = "ADOPT"
    EXTEND = "EXTEND"
    WRAP = "WRAP"
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    DEFER = "DEFER"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    name: str
    disposition: CapabilityDisposition
    entrypoint: str
    owner: str
    health_probe: str
    verifier: str
    risk_class: str
    evidence: str
    reason_code: str = ""

    def __post_init__(self) -> None:
        for name in ("name", "entrypoint", "owner", "health_probe", "verifier", "risk_class", "evidence"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        if not isinstance(self.disposition, CapabilityDisposition):
            object.__setattr__(self, "disposition", CapabilityDisposition(self.disposition))
        if self.disposition is CapabilityDisposition.REPAIR and not str(self.reason_code).strip():
            raise ValueError("REPAIR capabilities require a reason_code")
        object.__setattr__(self, "reason_code", str(self.reason_code).strip())

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "disposition": self.disposition.value,
            "entrypoint": self.entrypoint,
            "owner": self.owner,
            "health_probe": self.health_probe,
            "verifier": self.verifier,
            "risk_class": self.risk_class,
            "evidence": self.evidence,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class CapabilityInventory:
    records: tuple[CapabilityRecord, ...]

    def __post_init__(self) -> None:
        records = tuple(sorted(self.records, key=lambda item: item.name))
        if not all(isinstance(item, CapabilityRecord) for item in records):
            raise TypeError("records must contain CapabilityRecord values")
        if len({item.name for item in records}) != len(records):
            raise ValueError("capability names must be unique")
        object.__setattr__(self, "records", records)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CAPABILITY_INVENTORY_SCHEMA,
            "records": [item.to_dict() for item in self.records],
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["CAPABILITY_INVENTORY_SCHEMA", "CapabilityDisposition", "CapabilityRecord", "CapabilityInventory"]
