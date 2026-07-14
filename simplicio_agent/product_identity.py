"""Canonical product identity for Simplicio Agent.

Keep compatibility aliases and migration policy out of this module.  It names
only the target identity owned by issue #186 so identity-bearing contracts can
share one import-safe value object.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CanonicalProductIdentity:
    """Names the canonical product and its public technical surfaces."""

    product: str
    cli: str
    distribution: str
    python_namespace: str
    environment_prefix: str
    state_root: str
    protocol_prefix: str
    kernel: str


PRODUCT_IDENTITY = CanonicalProductIdentity(
    product="Simplicio Agent",
    cli="simplicio-agent",
    distribution="simplicio-agent",
    python_namespace="simplicio_agent",
    environment_prefix="SIMPLICIO_AGENT_",
    state_root="~/.simplicio/agent",
    protocol_prefix="simplicio.agent.",
    kernel="simplicio",
)


__all__ = ["CanonicalProductIdentity", "PRODUCT_IDENTITY"]
