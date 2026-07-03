"""
provider_mode.py — 3-mode operational contract for Simplicio Agent (issue #64).

The Simplicio Agent serves in three distinct roles with the same binary.
This module defines the contract and resolution logic for each mode.

Modes:
    1. STANDALONE — autonomous agent (Hermes default). Full LLM, local ladder.
       Triggered by CLI/gateway invocation. Uses own provider config.

    2. TOOL — deterministic executor only. ZERO LLM calls inside the agent
       for this request. Used when an external LLM calls via MCP for discrete
       operations (map, edit, gate, test, evidence).

    3. DELEGATED — full loop runner on behalf of a caller. LLM calls use the
       local ladder by default, or the caller's provider if explicitly passed
       AND authorized by the Action Gate.

Credential rule (security — non-negotiable):
    The caller's credential enters by explicit `provider_ref` in the MCP
    request, passes through the Action Gate (classify/authorize), is used
    ONLY for that session, is NEVER persisted to disk/config, and is REDACTED
    from all logs/evidence.
"""

from __future__ import annotations

import enum
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ProviderMode(enum.Enum):
    """The three provider operation modes."""

    STANDALONE = "standalone"
    """Autonomous mode — agent owns the full provider chain. Default for CLI/gateway."""

    TOOL = "tool"
    """Deterministic tool mode — NO LLM calls allowed. For MCP discrete operations."""

    DELEGATED = "delegated"
    """Delegated loop mode — uses local ladder or caller's provider_ref if gated."""


def resolve_mode(
    invocation_source: str = "cli",
    mcp_mode: Optional[str] = None,
) -> ProviderMode:
    """Resolve the operation mode based on invocation context."""
    if invocation_source in ("cli", "gateway"):
        return ProviderMode.STANDALONE
    if invocation_source in ("mcp", "stdio"):
        if mcp_mode == "tool":
            return ProviderMode.TOOL
        return ProviderMode.DELEGATED
    return ProviderMode.STANDALONE


def resolve_provider(
    mode: ProviderMode,
    provider_ref: Optional[str] = None,
    action_gate_authorized: bool = False,
) -> Optional[str]:
    """Resolve which provider to use based on mode and credential rules."""
    if mode == ProviderMode.TOOL:
        raise RuntimeError(
            "TOOL mode: LLM calls are forbidden. "
            "This operation must be deterministic only."
        )
    if mode == ProviderMode.DELEGATED and provider_ref is not None:
        if not action_gate_authorized:
            logger.warning(
                "Delegated mode: provider_ref=%r rejected by Action Gate. "
                "Falling back to local ladder.",
                provider_ref,
            )
            return None
        logger.info(
            "Delegated mode: using caller's provider_ref (gated + in-memory only)."
        )
        return provider_ref
    return None
