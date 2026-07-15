"""Canonical public machine identity for external contracts (issue #191).

MCP ``serverInfo``, User-Agent product tokens, telemetry/receipt component
fields and other *machine-facing* identity strings must all derive from one
source of truth so the shipped product is consistently ``Simplicio Agent``
across every external surface.  Keep branding literals out of the call sites;
import them here.

Internal-only identifiers (module names, env vars, state paths) are out of
scope — see :mod:`simplicio_agent.product_identity` for the full canonical
identity object and :mod:`simplicio_agent.compat` for deprecated aliases.
"""

from __future__ import annotations

import os
import platform
import sys

from .product_identity import PRODUCT_IDENTITY

__all__ = [
    "MCP_SERVER_NAME",
    "MCP_PRODUCT_TOKEN",
    "build_user_agent",
    "canonical_user_agent",
    "get_public_version",
    "product_display_name",
]

# Name advertised through MCP ``initialize``/``serverInfo``. Hosts, automations
# and MCP client catalogs key off this string, so it is the canonical product
# name, never a legacy alias.
MCP_SERVER_NAME: str = PRODUCT_IDENTITY.product

# Machine-token form of the product name for User-Agent / telemetry component
# fields.  A single camel-cased token (no spaces) is the conventional shape
# for HTTP/synthetic User-Agent product tokens.
MCP_PRODUCT_TOKEN: str = "SimplicioAgent"


def product_display_name() -> str:
    """Return the canonical human product name (``Simplicio Agent``)."""
    return PRODUCT_IDENTITY.product


def get_public_version(distribution: str = "simplicio-agent") -> str:
    """Return the installed public package version, or ``dev`` if unavailable.

    The version is read from distribution metadata, not from any internal
    module, so the reported number always matches what was actually shipped.
    """
    try:
        from importlib.metadata import version

        return version(distribution)
    except Exception:
        return "dev"


def build_user_agent(adapter_name: str, adapter_version: str) -> str:
    """Build a User-Agent fragment for a public adapter/component.

    Format::

        <adapter_name>/<adapter_version> (Python/<py>; <os>; <Product>/<ver>)

    The product token is always the canonical Simplicio Agent token, never a
    legacy brand, and no third party or user is attributed in the string.
    """
    py_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro}"
    )
    os_name = platform.system().lower()
    product_version = get_public_version()
    return (
        f"{adapter_name}/{adapter_version} "
        f"(Python/{py_version}; {os_name}; {MCP_PRODUCT_TOKEN}/{product_version})"
    )


def canonical_user_agent() -> str:
    """Return the product's own User-Agent (used for direct HTTP calls)."""
    return build_user_agent(MCP_PRODUCT_TOKEN, get_public_version())
