from __future__ import annotations

import copy

import pytest

from agent.schema_tiering import ExpansionLimitExceeded, build_schema_tier_catalog
from tools.registry import ToolRegistry


def _schema(name: str, description: str, marker: str) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {"marker": {"type": "string", "const": marker}},
        },
    }


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name, description in (
        ("common", "Common file operation"),
        ("rare", "Rare provider operation"),
        ("hidden", "Restricted operation"),
    ):
        registry.register(
            name=name,
            toolset="test",
            schema=_schema(name, description, name),
            handler=lambda _args: "ok",
            check_fn=(lambda: False) if name == "hidden" else (lambda: True),
        )
    return registry


def test_tiering_is_deterministic_and_authorization_is_applied_first():
    registry = _registry()
    first = build_schema_tier_catalog(
        registry,
        task="common file operation",
        core_tool_names=("common",),
        full_tier_limit=1,
    )
    second = build_schema_tier_catalog(
        registry,
        task="common file operation",
        core_tool_names=("common",),
        full_tier_limit=1,
    )
    assert [item.as_dict() for item in first.manifests] == [item.as_dict() for item in second.manifests]
    assert [item.name for item in first.manifests] == ["common", "rare"]
    assert first.manifests[0].tier == "full"
    assert all(item.name != "hidden" for item in first.manifests)


def test_rare_schema_is_absent_until_tool_view_and_then_exact():
    registry = _registry()
    catalog = build_schema_tier_catalog(registry, core_tool_names=("common",), full_tier_limit=1)
    prefix = catalog.stable_prefix()
    assert "rare" not in catalog.loaded_schema_names
    rare_prefix = next(item for item in prefix if item["function"]["name"] == "rare")
    assert "parameters" not in rare_prefix["function"]
    result = catalog.view("tool.view:rare")
    assert result.schema == registry.get_definitions({"rare"}, quiet=True)[0]["function"]
    assert result.receipt.cache_hit is False
    assert "rare" in catalog.loaded_schema_names


def test_expansion_cache_limit_and_stable_prefix():
    registry = _registry()
    catalog = build_schema_tier_catalog(registry, core_tool_names=("common",), full_tier_limit=1, max_expansions=1)
    before = copy.deepcopy(catalog.stable_prefix())
    first = catalog.expand_with_receipt("rare")
    second = catalog.expand_with_receipt("rare")
    assert first.receipt.cache_hit is False
    assert second.receipt.cache_hit is True
    assert second.receipt.schema_hash == first.receipt.schema_hash
    assert catalog.stable_prefix() == before
    with pytest.raises(ExpansionLimitExceeded):
        catalog.expand("common")


def test_registry_generation_changes_cache_key_without_mutating_frozen_prefix():
    registry = _registry()
    catalog = build_schema_tier_catalog(registry, core_tool_names=("common",), full_tier_limit=1, max_expansions=2)
    before = catalog.stable_prefix()
    first = catalog.expand_with_receipt("rare")
    registry.register(
        name="rare",
        toolset="test",
        schema=_schema("rare", "Rare provider operation v2", "changed"),
        handler=lambda _args: "ok",
        override=False,
    )
    changed = catalog.expand_with_receipt("rare")
    assert changed.receipt.generation != first.receipt.generation
    assert changed.receipt.cache_hit is False
    assert changed.schema["parameters"] != first.schema["parameters"]
    assert catalog.stable_prefix() == before


def test_unauthorized_view_does_not_leak_schema():
    registry = _registry()
    catalog = build_schema_tier_catalog(registry, core_tool_names=("common",), full_tier_limit=1)
    with pytest.raises(KeyError):
        catalog.view("tool.view:hidden")
