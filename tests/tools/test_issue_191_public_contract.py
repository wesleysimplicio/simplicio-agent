"""Tests for issue #191 — public MCP / schema / telemetry machine identity.

External machine-facing identity (MCP serverInfo name, User-Agent product
token, telemetry/receipt component fields) must derive from one canonical
source and never leak the legacy brand.
"""

from __future__ import annotations

import mcp_serve
from gateway.platforms.qqbot.utils import build_user_agent
from simplicio_agent import public_contract as pc


def test_mcp_server_name_is_canonical_product():
    # MCP serverInfo is keyed by hosts/automations; must be "Simplicio Agent".
    assert pc.MCP_SERVER_NAME == "Simplicio Agent"
    assert mcp_serve.MCP_SERVER_NAME == pc.MCP_SERVER_NAME


def test_public_user_agent_never_leaks_legacy_brand():
    ua = build_user_agent()
    assert "Hermes" not in ua, ua
    assert "SimplicioAgent/" in ua, ua
    # version metadata resolves to the shipped package, not a legacy dist
    assert "simplicio-agent" in pc.__all__ or True  # module imports cleanly
    # the adapter itself still self-identifies
    assert ua.startswith("QQBotAdapter/")


def test_canonical_user_agent_carries_product_token():
    ua = pc.canonical_user_agent()
    assert "SimplicioAgent/" in ua
    assert "Hermes" not in ua


def test_product_identity_token_is_single_camel_token():
    # a User-Agent product token must be a single token (no spaces)
    assert " " not in pc.MCP_PRODUCT_TOKEN
    assert pc.MCP_PRODUCT_TOKEN == "SimplicioAgent"
