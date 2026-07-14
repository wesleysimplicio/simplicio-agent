"""Public Simplicio Agent facade.

This package exposes stable product-facing imports without renaming the
underlying Hermes internals. The exported objects are the canonical runtime
classes themselves, not wrapper subclasses, so identity-sensitive code keeps
working unchanged.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from hermes_cli import __release_date__, __version__

__all__ = ["Agent", "CLI", "__release_date__", "__version__", "asolaria", "main"]

_EXPORTS: dict[str, tuple[str, str]] = {
    "Agent": ("run_agent", "AIAgent"),
    "CLI": ("cli", "HermesCLI"),
    "main": ("hermes_cli.main", "main"),
}

if TYPE_CHECKING:
    # Keep runtime imports lazy while giving type checkers the canonical
    # public names promised by this facade.
    from . import asolaria
    from cli import HermesCLI as CLI
    from hermes_cli.main import main
    from run_agent import AIAgent as Agent


def __getattr__(name: str) -> Any:
    if name == "asolaria":
        return import_module(f"{__name__}.asolaria")
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    return getattr(import_module(module_name), attr_name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
