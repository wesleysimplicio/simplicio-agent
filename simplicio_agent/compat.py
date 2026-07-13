"""Deprecated compatibility aliases for legacy Simplicio Agent imports."""

from __future__ import annotations

from importlib import import_module
import warnings
from typing import Any

__all__ = ["AIAgent", "HermesCLI"]

_EXPORTS = {
    "AIAgent": "Agent",
    "HermesCLI": "CLI",
}


def __getattr__(name: str) -> Any:
    canonical_name = _EXPORTS.get(name)
    if canonical_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    public_module = import_module("simplicio_agent")
    value = getattr(public_module, canonical_name)
    warnings.warn(
        (
            f"simplicio_agent.compat.{name} is deprecated; "
            f"use simplicio_agent.{canonical_name} instead."
        ),
        DeprecationWarning,
        stacklevel=2,
    )
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
