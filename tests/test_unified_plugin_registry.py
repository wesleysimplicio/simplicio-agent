"""Tests for agent/plugins/unified_registry.py — Issue #43."""
import pytest

from agent.plugins.unified_registry import (
    PluginAlreadyRegisteredError,
    PluginManifest,
    PluginNotFoundError,
    UnifiedPluginRegistry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry() -> UnifiedPluginRegistry:
    return UnifiedPluginRegistry()


@pytest.fixture()
def sample_manifest() -> PluginManifest:
    return PluginManifest(
        name="test_plugin",
        version="0.1.0",
        description="A test plugin",
        entry_point="test_pkg.test_plugin:main",
        capabilities=["search", "summarize"],
    )


@pytest.fixture()
def gated_manifest() -> PluginManifest:
    return PluginManifest(
        name="gated_plugin",
        version="1.0.0",
        description="A service-gated plugin",
        entry_point="gated_pkg.gated:main",
        capabilities=["external_api"],
        gated=True,
    )


# ---------------------------------------------------------------------------
# Test: registration and retrieval
# ---------------------------------------------------------------------------

def test_register_and_get_plugin(registry, sample_manifest):
    """Registering a manifest makes it retrievable by name."""
    registry.register(sample_manifest)
    retrieved = registry.get_plugin("test_plugin")
    assert retrieved.name == "test_plugin"
    assert retrieved.version == "0.1.0"
    assert "search" in retrieved.capabilities


def test_list_plugins_empty_initially(registry):
    """A fresh registry lists no plugins."""
    assert registry.list_plugins() == []


def test_list_plugins_after_registration(registry, sample_manifest, gated_manifest):
    """list_plugins returns all registered manifests."""
    registry.register(sample_manifest)
    registry.register(gated_manifest)
    names = {p.name for p in registry.list_plugins()}
    assert names == {"test_plugin", "gated_plugin"}


# ---------------------------------------------------------------------------
# Test: unregister
# ---------------------------------------------------------------------------

def test_unregister_removes_plugin(registry, sample_manifest):
    """Unregistering a plugin removes it from the registry."""
    registry.register(sample_manifest)
    assert "test_plugin" in registry
    registry.unregister("test_plugin")
    assert "test_plugin" not in registry


def test_unregister_returns_manifest(registry, sample_manifest):
    """unregister() returns the removed manifest."""
    registry.register(sample_manifest)
    removed = registry.unregister("test_plugin")
    assert removed.name == "test_plugin"


def test_unregister_unknown_raises(registry):
    """Unregistering an unknown plugin raises PluginNotFoundError."""
    with pytest.raises(PluginNotFoundError):
        registry.unregister("nonexistent")


# ---------------------------------------------------------------------------
# Test: duplicate registration
# ---------------------------------------------------------------------------

def test_duplicate_registration_raises(registry, sample_manifest):
    """Registering the same name twice raises PluginAlreadyRegisteredError."""
    registry.register(sample_manifest)
    duplicate = PluginManifest(
        name="test_plugin",
        version="9.9.9",
        description="Duplicate",
        entry_point="other:main",
    )
    with pytest.raises(PluginAlreadyRegisteredError):
        registry.register(duplicate)


# ---------------------------------------------------------------------------
# Test: service-gated tools
# ---------------------------------------------------------------------------

def test_is_gated_false_for_normal_plugin(registry, sample_manifest):
    """Non-gated plugins report is_gated() == False."""
    registry.register(sample_manifest)
    assert registry.is_gated("test_plugin") is False


def test_is_gated_true_for_gated_plugin(registry, gated_manifest):
    """Service-gated plugins report is_gated() == True."""
    registry.register(gated_manifest)
    assert registry.is_gated("gated_plugin") is True


def test_is_gated_unknown_raises(registry):
    """is_gated() raises PluginNotFoundError for unknown plugins."""
    with pytest.raises(PluginNotFoundError):
        registry.is_gated("unknown")


# ---------------------------------------------------------------------------
# Test: __len__ and __contains__
# ---------------------------------------------------------------------------

def test_len_and_contains(registry, sample_manifest):
    assert len(registry) == 0
    registry.register(sample_manifest)
    assert len(registry) == 1
    assert "test_plugin" in registry
    assert "other" not in registry


# ---------------------------------------------------------------------------
# Test: get_plugin raises for missing
# ---------------------------------------------------------------------------

def test_get_plugin_unknown_raises(registry):
    with pytest.raises(PluginNotFoundError):
        registry.get_plugin("missing")
