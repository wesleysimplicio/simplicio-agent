"""Persistent, privacy-preserving registry for local orchestration supervisors."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


REGISTRY_SCHEMA = "simplicio.supervisor-registry/v1"


class SupervisorRegistryError(ValueError):
    """Base error for invalid or conflicting supervisor registrations."""


class SupervisorConflict(SupervisorRegistryError):
    """Raised when an id is reused by a different hardware fingerprint."""


def hardware_fingerprint(
    *,
    machine: str | None = None,
    processor: str | None = None,
    node: int | None = None,
    cpu_count: int | None = None,
    salt: str | None = None,
) -> str:
    """Return a stable, non-reversible fingerprint without storing raw hardware data."""

    material = {
        "schema": REGISTRY_SCHEMA,
        "machine": machine if machine is not None else platform.machine(),
        "processor": processor if processor is not None else platform.processor(),
        "node": node if node is not None else uuid.getnode(),
        "cpu_count": cpu_count if cpu_count is not None else (os.cpu_count() or 0),
        "salt": salt if salt is not None else os.getenv("SIMPLICIO_SUPERVISOR_FINGERPRINT_SALT", "simplicio-v1"),
    }
    payload = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class SupervisorDescriptor:
    supervisor_id: str
    role: str
    hardware_fingerprint: str
    capabilities: tuple[str, ...] = ()
    last_seen_ns: int = 0

    def __post_init__(self) -> None:
        for name in ("supervisor_id", "role", "hardware_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SupervisorRegistryError(f"{name} must be non-empty")
        if not self.hardware_fingerprint.startswith("sha256:"):
            raise SupervisorRegistryError("hardware_fingerprint must be sha256-pinned")
        capabilities = tuple(sorted(set(self.capabilities)))
        if any(not isinstance(item, str) or not item.strip() for item in capabilities):
            raise SupervisorRegistryError("capabilities must contain non-empty strings")
        object.__setattr__(self, "capabilities", capabilities)
        if not isinstance(self.last_seen_ns, int) or self.last_seen_ns <= 0:
            raise SupervisorRegistryError("last_seen_ns must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "supervisor_id": self.supervisor_id,
            "role": self.role,
            "hardware_fingerprint": self.hardware_fingerprint,
            "capabilities": list(self.capabilities),
            "last_seen_ns": self.last_seen_ns,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SupervisorDescriptor":
        return cls(
            supervisor_id=str(value["supervisor_id"]),
            role=str(value["role"]),
            hardware_fingerprint=str(value["hardware_fingerprint"]),
            capabilities=tuple(str(item) for item in value.get("capabilities", ())),
            last_seen_ns=int(value["last_seen_ns"]),
        )


class SupervisorRegistry:
    """Small atomic JSON registry; raw hardware identifiers never leave the process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list(self) -> tuple[SupervisorDescriptor, ...]:
        records = self._read()
        return tuple(records[key] for key in sorted(records))

    def get(self, supervisor_id: str) -> SupervisorDescriptor | None:
        return self._read().get(supervisor_id)

    def register(
        self,
        supervisor_id: str,
        *,
        role: str,
        capabilities: Sequence[str] = (),
        fingerprint: str | None = None,
        now_ns: int | None = None,
    ) -> SupervisorDescriptor:
        records = self._read()
        current = records.get(supervisor_id)
        resolved_fingerprint = fingerprint or hardware_fingerprint()
        if current is not None and current.hardware_fingerprint != resolved_fingerprint:
            raise SupervisorConflict(
                f"supervisor {supervisor_id!r} is already registered to another hardware fingerprint"
            )
        descriptor = SupervisorDescriptor(
            supervisor_id=supervisor_id,
            role=role,
            hardware_fingerprint=resolved_fingerprint,
            capabilities=tuple(capabilities),
            last_seen_ns=now_ns or time.time_ns(),
        )
        records[supervisor_id] = descriptor
        self._write(records)
        return descriptor

    def unregister(self, supervisor_id: str) -> bool:
        records = self._read()
        if supervisor_id not in records:
            return False
        del records[supervisor_id]
        self._write(records)
        return True

    def _read(self) -> dict[str, SupervisorDescriptor]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != REGISTRY_SCHEMA:
                raise SupervisorRegistryError("unsupported supervisor registry schema")
            raw = payload.get("supervisors", {})
            if not isinstance(raw, dict):
                raise SupervisorRegistryError("supervisors must be an object")
            records = {key: SupervisorDescriptor.from_dict(value) for key, value in raw.items()}
            if any(key != descriptor.supervisor_id for key, descriptor in records.items()):
                raise SupervisorRegistryError("registry key and supervisor_id differ")
            return records
        except (OSError, TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, SupervisorRegistryError):
                raise
            raise SupervisorRegistryError(f"invalid supervisor registry: {exc}") from exc

    def _write(self, records: Mapping[str, SupervisorDescriptor]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": REGISTRY_SCHEMA,
            "supervisors": {key: records[key].to_dict() for key in sorted(records)},
        }
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


__all__ = [
    "REGISTRY_SCHEMA",
    "SupervisorConflict",
    "SupervisorDescriptor",
    "SupervisorRegistry",
    "SupervisorRegistryError",
    "hardware_fingerprint",
]
