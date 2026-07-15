"""Unified Plugin Registry — Issue #43.

Provides a common plugin API for Simplicio Agent.
Stdlib only, no external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PluginManifest:
    """Describes a plugin's identity and capabilities."""

    name: str
    version: str
    description: str
    entry_point: str
    capabilities: List[str] = field(default_factory=list)
    # If True the tool is service-gated (requires external service auth)
    gated: bool = False


class PluginNotFoundError(KeyError):
    """Raised when a plugin lookup fails."""


class PluginAlreadyRegisteredError(ValueError):
    """Raised when a plugin name is already registered."""


class UnifiedPluginRegistry:
    """Central registry for all Simplicio Agent plugins.

    Usage::

        registry = UnifiedPluginRegistry()
        manifest = PluginManifest(
            name="my_plugin",
            version="1.0.0",
            description="Does something useful",
            entry_point="my_pkg.my_plugin:main",
            capabilities=["search"],
        )
        registry.register(manifest)
        plugin = registry.get_plugin("my_plugin")
        registry.unregister("my_plugin")
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, PluginManifest] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, manifest: PluginManifest) -> None:
        """Register a plugin manifest.

        Raises:
            PluginAlreadyRegisteredError: if a plugin with the same name is
                already registered.
        """
        if manifest.name in self._plugins:
            raise PluginAlreadyRegisteredError(
                f"Plugin '{manifest.name}' is already registered. "
                "Unregister it first or use a different name."
            )
        self._plugins[manifest.name] = manifest

    def unregister(self, name: str) -> PluginManifest:
        """Remove a plugin from the registry and return its manifest.

        Raises:
            PluginNotFoundError: if no plugin with *name* is registered.
        """
        if name not in self._plugins:
            raise PluginNotFoundError(f"Plugin '{name}' is not registered.")
        return self._plugins.pop(name)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_plugins(self) -> List[PluginManifest]:
        """Return a snapshot list of all registered plugin manifests."""
        return list(self._plugins.values())

    def get_plugin(self, name: str) -> PluginManifest:
        """Look up a plugin by name.

        Raises:
            PluginNotFoundError: if no plugin with *name* is registered.
        """
        try:
            return self._plugins[name]
        except KeyError:
            raise PluginNotFoundError(f"Plugin '{name}' is not registered.")

    def is_gated(self, name: str) -> bool:
        """Return True if the plugin is service-gated (requires external auth).

        Raises:
            PluginNotFoundError: if no plugin with *name* is registered.
        """
        return self.get_plugin(name).gated

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: object) -> bool:
        return name in self._plugins

    def __repr__(self) -> str:
        names = list(self._plugins)
        return f"<UnifiedPluginRegistry plugins={names}>"
