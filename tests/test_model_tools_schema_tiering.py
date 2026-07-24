from __future__ import annotations

import json

import pytest

import model_tools
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


@pytest.fixture
def isolated_manifest(monkeypatch):
    registry = _registry()
    monkeypatch.setattr(model_tools, "registry", registry)
    monkeypatch.setattr(
        model_tools,
        "_compute_tool_definitions",
        lambda *_args, **_kwargs: registry.get_definitions(
            set(registry.get_all_tool_names()), quiet=True
        ),
    )
    model_tools._clear_tool_defs_cache()
    yield registry
    model_tools._clear_tool_defs_cache()


def _manifest(session_id: str):
    return model_tools.get_tool_definitions(
        quiet_mode=True,
        skip_tool_search_assembly=True,
        schema_tiering=True,
        schema_tiering_task="common file operation",
        schema_tiering_full_tier_limit=1,
        schema_tiering_max_expansions=1,
        schema_tiering_session_id=session_id,
    )


def test_public_manifest_wires_tiering_and_filters_permissions(isolated_manifest):
    manifest = _manifest("permission-session")
    names = [item["function"]["name"] for item in manifest]

    assert names == ["common", "rare", "tool.view"]
    assert "hidden" not in names
    rare = next(item for item in manifest if item["function"]["name"] == "rare")
    assert "parameters" not in rare["function"]
    assert rare["function"]["x-tool-view"] == "tool.view:rare"


def test_tool_view_dispatch_returns_receipt_and_preserves_stable_prefix(isolated_manifest):
    session_id = "view-session"
    before = _manifest(session_id)
    first = json.loads(
        model_tools.handle_function_call(
            "tool.view",
            {"handle": "tool.view:rare"},
            session_id=session_id,
        )
    )
    second = json.loads(
        model_tools.handle_function_call(
            "tool.view",
            {"handle": "tool.view:rare"},
            session_id=session_id,
        )
    )
    after = _manifest(session_id)

    assert first["schema"]["name"] == "rare"
    assert first["schema"]["parameters"]["properties"]["marker"]["const"] == "rare"
    assert first["receipt"]["cache_hit"] is False
    assert second["receipt"]["cache_hit"] is True
    assert after == before


def test_tool_view_rejects_unauthorized_handles_and_bounds_expansion(isolated_manifest):
    session_id = "bounded-session"
    _manifest(session_id)

    hidden = json.loads(model_tools.view_tool_schema("tool.view:hidden", session_id))
    assert hidden["error_type"] == "tool_view"
    assert "unknown tool view handle" in hidden["error"]

    json.loads(model_tools.view_tool_schema("tool.view:rare", session_id))
    exhausted = json.loads(model_tools.view_tool_schema("tool.view:common", session_id))
    assert exhausted["error_type"] == "tool_view"
    assert "expansion limit reached" in exhausted["error"]
