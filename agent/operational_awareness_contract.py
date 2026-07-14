"""Bounded operational-awareness contract for the consciousness epic."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


OPERATIONAL_AWARENESS_SCHEMA = "simplicio.operational-awareness/v1"


def _text(value: Any, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} must be non-empty")
    return result


@dataclass(frozen=True, slots=True)
class OperationalAwarenessContract:
    """Small, replayable awareness envelope; it never grants authority."""

    identity_ref: str
    goal_ref: str
    run_id: str
    phase: str
    self_state: Mapping[str, Any]
    world_state: Mapping[str, Any]
    attention: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("identity_ref", "goal_ref", "run_id", "phase"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("self_state", "world_state"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TypeError(f"{name} must be a mapping")
            object.__setattr__(self, name, dict(sorted(value.items())))
        for name in ("attention", "unknowns", "conflicts"):
            values = tuple(sorted({_text(item, name) for item in getattr(self, name)}))
            object.__setattr__(self, name, values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OPERATIONAL_AWARENESS_SCHEMA,
            "identity_ref": self.identity_ref,
            "goal_ref": self.goal_ref,
            "run_id": self.run_id,
            "phase": self.phase,
            "self_state": dict(self.self_state),
            "world_state": dict(self.world_state),
            "attention": list(self.attention),
            "unknowns": list(self.unknowns),
            "conflicts": list(self.conflicts),
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["OPERATIONAL_AWARENESS_SCHEMA", "OperationalAwarenessContract"]
