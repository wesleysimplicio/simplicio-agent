"""Small lazy prompt surface for the #318 native prompt slice.

This module is an adapter around the existing prompt-economy catalog.  It
does not replace or duplicate #196: full tool parity remains the caller's
responsibility, while this broker exposes only handles until a schema is
explicitly requested.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from agent.prompt_economy import pin_capability_bundle

PRIMITIVES = ("recall", "inspect", "decide", "act", "verify")
FIXED_SCHEMA_MAX_BYTES = 1_024


class SchemaBudgetExceeded(ValueError):
    """Raised when a fixed primitive schema would exceed its byte budget."""


@dataclass(frozen=True)
class CapabilityParityReceipt:
    expected: tuple[str, ...]
    actual: tuple[str, ...]
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    schema_bytes: int
    schema_sha256: str
    cache_stable: bool = True

    @property
    def equivalent(self) -> bool:
        return not self.missing and not self.extra

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": list(self.expected),
            "actual": list(self.actual),
            "missing": list(self.missing),
            "extra": list(self.extra),
            "schema_bytes": self.schema_bytes,
            "schema_sha256": self.schema_sha256,
            "cache_stable": self.cache_stable,
            "equivalent": self.equivalent,
        }


@dataclass(frozen=True)
class PromptCapsule:
    """A deterministic, content-addressed prompt envelope."""

    primitives: tuple[str, ...]
    context_ids: tuple[str, ...]
    delta_ids: tuple[str, ...]
    schema: tuple[Mapping[str, Any], ...]
    prompt_tokens: int
    schema_bytes: int
    prefix_sha256: str
    cache_stable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "primitives": list(self.primitives),
            "context_ids": list(self.context_ids),
            "delta_ids": list(self.delta_ids),
            "schema": list(self.schema),
            "prompt_tokens": self.prompt_tokens,
            "schema_bytes": self.schema_bytes,
            "prefix_sha256": self.prefix_sha256,
            "cache_stable": self.cache_stable,
        }


_PRIMITIVE_SCHEMA: dict[str, dict[str, Any]] = {
    name: {
        "name": name,
        "description": f"{name} a content-addressed task artifact.",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    }
    for name in PRIMITIVES
}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class CapabilityBroker:
    """Resolve capability handles and load schemas on demand."""

    def __init__(self, capabilities: Iterable[Mapping[str, Any]] = ()) -> None:
        self._capabilities = {
            str(item.get("name")): dict(item)
            for item in capabilities
            if item.get("name")
        }

    def handles(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))

    def load_schema(self, name: str) -> Mapping[str, Any]:
        if name not in self._capabilities:
            raise KeyError(name)
        return dict(self._capabilities[name])

    def parity_receipt(self, expected: Iterable[str]) -> CapabilityParityReceipt:
        expected_names = tuple(sorted(set(expected)))
        actual = self.handles()
        schema = [self.load_schema(name) for name in actual]
        encoded = _stable_json(schema).encode("utf-8")
        return CapabilityParityReceipt(
            expected=expected_names,
            actual=actual,
            missing=tuple(name for name in expected_names if name not in actual),
            extra=tuple(name for name in actual if name not in expected_names),
            schema_bytes=len(encoded),
            schema_sha256=hashlib.sha256(encoded).hexdigest(),
        )


def primitive_schemas(
    names: Iterable[str] = PRIMITIVES,
) -> tuple[Mapping[str, Any], ...]:
    requested = set(names)
    selected = tuple(name for name in PRIMITIVES if name in requested)
    return tuple(dict(_PRIMITIVE_SCHEMA[name]) for name in selected)


def build_capsule(
    *,
    context_ids: Iterable[str] = (),
    delta_ids: Iterable[str] = (),
    primitive_names: Iterable[str] = PRIMITIVES,
) -> PromptCapsule:
    """Build a stable lazy capsule and reject schema drift before sending."""

    requested = set(primitive_names)
    primitives = tuple(name for name in PRIMITIVES if name in requested)
    schemas = primitive_schemas(primitives)
    encoded_schema = _stable_json(schemas).encode("utf-8")
    if len(encoded_schema) > FIXED_SCHEMA_MAX_BYTES:
        raise SchemaBudgetExceeded(f"primitive schema is {len(encoded_schema)} bytes")
    contexts = tuple(sorted(set(context_ids)))
    deltas = tuple(sorted(set(delta_ids)))
    prefix = _stable_json({
        "primitives": primitives,
        "context_ids": contexts,
        "delta_ids": deltas,
    })
    prompt_tokens = max(1, (len(prefix.encode("utf-8")) + 3) // 4)
    return PromptCapsule(
        primitives=primitives,
        context_ids=contexts,
        delta_ids=deltas,
        schema=schemas,
        prompt_tokens=prompt_tokens,
        schema_bytes=len(encoded_schema),
        prefix_sha256=hashlib.sha256(prefix.encode("utf-8")).hexdigest(),
    )


def pin_existing_capabilities(
    tools: Iterable[Mapping[str, Any]], task: str = ""
) -> list[dict[str, Any]]:
    """Reuse #196's full-set ordering helper without reducing tool parity."""

    return pin_capability_bundle(list(tools), task=task)


__all__ = [
    "CapabilityBroker",
    "CapabilityParityReceipt",
    "FIXED_SCHEMA_MAX_BYTES",
    "PRIMITIVES",
    "PromptCapsule",
    "SchemaBudgetExceeded",
    "build_capsule",
    "pin_existing_capabilities",
    "primitive_schemas",
]
