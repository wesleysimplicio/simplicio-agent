"""Deterministic tool-schema tiering with bounded lazy expansion.

The catalog is a session snapshot.  Permission filtering is delegated to the
existing tool registry before tier assignment, while rare schemas remain out
of the stable prefix until an explicit ``tool.view:<name>`` expansion.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

DEFAULT_FULL_TIER_LIMIT = 8
DEFAULT_EXPANSION_LIMIT = 3
_SUMMARY_LIMIT = 160


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1}


def _summary(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:_SUMMARY_LIMIT].rstrip()


@dataclass(frozen=True)
class ToolSchemaManifest:
    name: str
    description: str
    tier: str
    handle: str
    schema_hash: str
    score: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tier": self.tier,
            "handle": self.handle,
            "schema_hash": self.schema_hash,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExpansionReceipt:
    name: str
    handle: str
    generation: int
    schema_hash: str
    cache_hit: bool
    expansion_number: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "handle": self.handle,
            "generation": self.generation,
            "schema_hash": self.schema_hash,
            "cache_hit": self.cache_hit,
            "expansion_number": self.expansion_number,
        }


@dataclass(frozen=True)
class ExpansionResult:
    schema: Mapping[str, Any]
    receipt: ExpansionReceipt


class ExpansionLimitExceeded(RuntimeError):
    """Raised when a session exceeds its explicit lazy-expansion budget."""


class SchemaTierCatalog:
    """Frozen manifest plus a generation-aware lazy schema cache."""

    def __init__(
        self,
        registry: Any,
        manifests: Sequence[ToolSchemaManifest],
        full_schemas: Mapping[str, Mapping[str, Any]],
        generation: int,
        max_expansions: int,
    ) -> None:
        self._registry = registry
        self._manifests = tuple(manifests)
        self._by_name = {item.name: item for item in self._manifests}
        self._full_schemas = {name: deepcopy(schema) for name, schema in full_schemas.items()}
        self._stable_prefix = self._render_prefix()
        self._generation = generation
        self._max_expansions = max_expansions
        self._expansions_used = 0
        self._cache: dict[tuple[int, str, str], Mapping[str, Any]] = {}

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def manifests(self) -> tuple[ToolSchemaManifest, ...]:
        return self._manifests

    @property
    def expansions_used(self) -> int:
        return self._expansions_used

    @property
    def loaded_schema_names(self) -> tuple[str, ...]:
        names = set(self._full_schemas)
        names.update(name for _generation, name, _schema_hash in self._cache)
        return tuple(sorted(names))

    def _render_prefix(self) -> tuple[dict[str, Any], ...]:
        rendered = []
        for manifest in self._manifests:
            if manifest.tier == "full":
                rendered.append(deepcopy(self._full_schemas[manifest.name]))
                continue
            rendered.append(
                {
                    "type": "function",
                    "function": {
                        "name": manifest.name,
                        "description": manifest.description,
                        "x-tool-tier": "rare",
                        "x-tool-view": manifest.handle,
                        "x-schema-sha256": manifest.schema_hash,
                    },
                }
            )
        return tuple(rendered)

    def stable_prefix(self) -> list[dict[str, Any]]:
        """Return a copy of the unchanged session prefix."""
        return deepcopy(self._stable_prefix)

    def _current_generation(self) -> int:
        return int(getattr(self._registry, "_generation", self._generation))

    def expand_with_receipt(self, name: str) -> ExpansionResult:
        manifest = self._by_name.get(name)
        if manifest is None:
            raise KeyError(f"tool not in session catalog: {name}")
        definitions = self._registry.get_definitions({name}, quiet=True)
        if len(definitions) != 1:
            raise KeyError(f"tool unavailable or unauthorized: {name}")
        schema = definitions[0].get("function")
        if not isinstance(schema, Mapping):
            raise TypeError(f"registry returned an invalid schema for {name!r}")
        schema_hash = _canonical_hash(schema)
        generation = self._current_generation()
        cache_key = (generation, name, schema_hash)
        cached = self._cache.get(cache_key)
        if cached is not None:
            receipt = ExpansionReceipt(
                name=name,
                handle=manifest.handle,
                generation=generation,
                schema_hash=schema_hash,
                cache_hit=True,
                expansion_number=self._expansions_used,
            )
            return ExpansionResult(deepcopy(cached), receipt)
        if self._expansions_used >= self._max_expansions:
            raise ExpansionLimitExceeded(
                f"lazy expansion limit reached ({self._max_expansions})"
            )
        cached = deepcopy(dict(schema))
        self._cache[cache_key] = cached
        self._expansions_used += 1
        receipt = ExpansionReceipt(
            name=name,
            handle=manifest.handle,
            generation=generation,
            schema_hash=schema_hash,
            cache_hit=False,
            expansion_number=self._expansions_used,
        )
        return ExpansionResult(deepcopy(cached), receipt)

    def expand(self, name: str) -> Mapping[str, Any]:
        return self.expand_with_receipt(name).schema

    def view(self, handle: str) -> ExpansionResult:
        name = handle.removeprefix("tool.view:")
        manifest = self._by_name.get(name)
        if manifest is None or manifest.handle != handle:
            raise KeyError(f"unknown tool view handle: {handle}")
        return self.expand_with_receipt(name)


def build_schema_tier_catalog(
    registry: Any,
    *,
    task: str = "",
    enabled_tool_names: Sequence[str] | None = None,
    core_tool_names: Sequence[str] = (),
    frequent_tool_names: Sequence[str] = (),
    risk_tool_names: Sequence[str] = (),
    usage_counts: Mapping[str, int] | None = None,
    full_tier_limit: int = DEFAULT_FULL_TIER_LIMIT,
    max_expansions: int = DEFAULT_EXPANSION_LIMIT,
) -> SchemaTierCatalog:
    """Build a deterministic, permission-filtered session catalog."""
    if full_tier_limit < 0:
        raise ValueError("full_tier_limit must be non-negative")
    if max_expansions < 0:
        raise ValueError("max_expansions must be non-negative")
    requested = set(enabled_tool_names or registry.get_all_tool_names())
    definitions = registry.get_definitions(requested, quiet=True)
    by_name = {
        item["function"]["name"]: item
        for item in definitions
        if isinstance(item.get("function"), Mapping) and item["function"].get("name")
    }
    core = set(core_tool_names)
    frequent = set(frequent_tool_names)
    risk = set(risk_tool_names)
    counts = usage_counts or {}
    task_tokens = _tokens(task)
    scored: list[tuple[int, int, str, str, Mapping[str, Any]]] = []
    for name in sorted(by_name):
        function = by_name[name]["function"]
        description = _summary(function.get("description", ""))
        overlap = len(task_tokens & _tokens(f"{name} {description}"))
        usage = max(0, int(counts.get(name, 0)))
        score = usage + (100 if name in core else 0) + (50 if name in frequent else 0)
        score += 25 if name in risk else 0
        score += overlap * 10
        score += max(0, 10 - len(json.dumps(function, ensure_ascii=False)) // 256)
        reasons = []
        if name in core:
            reasons.append("core")
        if name in frequent:
            reasons.append("frequent")
        if name in risk:
            reasons.append("risk")
        if usage:
            reasons.append(f"usage={usage}")
        if overlap:
            reasons.append(f"task-overlap={overlap}")
        if not reasons:
            reasons.append("deterministic-size-rank")
        scored.append((score, usage, name, ";".join(reasons), function))
    full_names = {item[2] for item in sorted(scored, key=lambda item: (-item[0], -item[1], item[2]))[:full_tier_limit]}
    manifests = []
    full_schemas = {}
    for score, _usage, name, reason, function in sorted(scored, key=lambda item: item[2]):
        tier = "full" if name in full_names else "rare"
        schema_hash = _canonical_hash(function)
        manifests.append(
            ToolSchemaManifest(
                name=name,
                description=_summary(function.get("description", "")),
                tier=tier,
                handle=f"tool.view:{name}",
                schema_hash=schema_hash,
                score=score,
                reason=reason if tier == "full" else f"{reason};below-full-tier-limit",
            )
        )
        if tier == "full":
            full_schemas[name] = by_name[name]
    generation = int(getattr(registry, "_generation", 0))
    return SchemaTierCatalog(registry, manifests, full_schemas, generation, max_expansions)


__all__ = [
    "DEFAULT_EXPANSION_LIMIT",
    "DEFAULT_FULL_TIER_LIMIT",
    "ExpansionLimitExceeded",
    "ExpansionReceipt",
    "ExpansionResult",
    "SchemaTierCatalog",
    "ToolSchemaManifest",
    "build_schema_tier_catalog",
]
