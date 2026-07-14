"""Small lazy prompt surface for the #318 native prompt slice.

This module is an adapter around the existing prompt-economy catalog.  It
does not replace or duplicate #196: full tool parity remains the caller's
responsibility, while this broker exposes only handles until a schema is
explicitly requested.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from agent.prompt_economy import pin_capability_bundle

PRIMITIVES = ("recall", "inspect", "decide", "act", "verify")
FIXED_SCHEMA_MAX_BYTES = 1_024
PROMPT_SCHEMA_VERSION = "simplicio.agent.prompt.microkernel/v1"
_MAX_ID_BYTES = 256

# These are intentionally a fixed, content-free boundary.  A boundary names
# the kind of work a tool may perform; it does not execute the tool or infer
# permissions.  Keeping this table here makes the compact prompt surface
# auditable without importing the controller or tool registry.
PRIMITIVE_BOUNDARIES = {name: name for name in PRIMITIVES}


class SchemaBudgetExceeded(ValueError):
    """Raised when a fixed primitive schema would exceed its byte budget."""


def _canonical_ids(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    """Return sorted, unique opaque IDs while rejecting unstable values."""

    result: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must contain non-empty strings")
        if value != value.strip() or any(char.isspace() for char in value):
            raise ValueError(f"{field_name} may not contain whitespace")
        if any(ord(char) < 32 for char in value):
            raise ValueError(f"{field_name} may not contain control characters")
        if len(value.encode("utf-8")) > _MAX_ID_BYTES:
            raise ValueError(f"{field_name} IDs must be at most {_MAX_ID_BYTES} bytes")
        result.add(value)
    return tuple(sorted(result))


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
class CapabilityExpansionReceipt:
    """Deterministic evidence for one on-demand capability expansion."""

    capability_id: str
    boundary: str
    schema_bytes: int
    schema_sha256: str
    cache_stable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "boundary": self.boundary,
            "schema_bytes": self.schema_bytes,
            "schema_sha256": self.schema_sha256,
            "cache_stable": self.cache_stable,
        }


@dataclass(frozen=True)
class PromptCapsuleReceipt:
    """Stable local receipt for a capsule's IDs, deltas, and fixed schema."""

    schema_version: str
    context_ids: tuple[str, ...]
    delta_ids: tuple[str, ...]
    schema_bytes: int
    schema_sha256: str
    prefix_sha256: str
    cache_stable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context_ids": list(self.context_ids),
            "delta_ids": list(self.delta_ids),
            "schema_bytes": self.schema_bytes,
            "schema_sha256": self.schema_sha256,
            "prefix_sha256": self.prefix_sha256,
            "cache_stable": self.cache_stable,
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
    schema_version: str = PROMPT_SCHEMA_VERSION
    schema_sha256: str = ""

    @property
    def receipt(self) -> PromptCapsuleReceipt:
        return PromptCapsuleReceipt(
            schema_version=self.schema_version,
            context_ids=self.context_ids,
            delta_ids=self.delta_ids,
            schema_bytes=self.schema_bytes,
            schema_sha256=self.schema_sha256,
            prefix_sha256=self.prefix_sha256,
            cache_stable=self.cache_stable,
        )

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
            "schema_version": self.schema_version,
            "schema_sha256": self.schema_sha256,
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
        self._capabilities: dict[str, dict[str, Any]] = {}
        for item in capabilities:
            name = self._tool_name(item)
            if name:
                self._capabilities[name] = deepcopy(dict(item))

    @staticmethod
    def _tool_name(item: Mapping[str, Any]) -> str:
        name = item.get("name")
        if isinstance(name, str) and name:
            return name
        function = item.get("function")
        if isinstance(function, Mapping):
            name = function.get("name")
            if isinstance(name, str) and name:
                return name
        return ""

    def handles(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))

    def load_schema(self, name: str) -> Mapping[str, Any]:
        if name not in self._capabilities:
            raise KeyError(name)
        return deepcopy(self._capabilities[name])

    # ``expand`` is the broker vocabulary used by callers; retain
    # ``load_schema`` as the explicit compatibility spelling.
    expand = load_schema

    def expand_with_receipt(
        self, name: str
    ) -> tuple[Mapping[str, Any], CapabilityExpansionReceipt]:
        schema = self.load_schema(name)
        encoded = _stable_json(schema).encode("utf-8")
        return schema, CapabilityExpansionReceipt(
            capability_id=name,
            boundary=PRIMITIVE_BOUNDARIES.get(name, "capability"),
            schema_bytes=len(encoded),
            schema_sha256=hashlib.sha256(encoded).hexdigest(),
        )

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
    contexts = _canonical_ids(context_ids, "context_ids")
    deltas = _canonical_ids(delta_ids, "delta_ids")
    schema_sha256 = hashlib.sha256(encoded_schema).hexdigest()
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
        schema_sha256=schema_sha256,
    )


def pin_existing_capabilities(
    tools: Iterable[Mapping[str, Any]], task: str = ""
) -> list[dict[str, Any]]:
    """Reuse #196's full-set ordering helper without reducing tool parity."""

    return pin_capability_bundle(list(tools), task=task)


__all__ = [
    "CapabilityBroker",
    "CapabilityParityReceipt",
    "CapabilityExpansionReceipt",
    "FIXED_SCHEMA_MAX_BYTES",
    "PRIMITIVE_BOUNDARIES",
    "PRIMITIVES",
    "PromptCapsule",
    "PromptCapsuleReceipt",
    "PROMPT_SCHEMA_VERSION",
    "SchemaBudgetExceeded",
    "build_capsule",
    "pin_existing_capabilities",
    "primitive_schemas",
]
