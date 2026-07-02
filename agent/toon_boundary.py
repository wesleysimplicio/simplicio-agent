"""TOON boundary conversion — the tool_executor chokepoint (issue #16).

Individual tool handlers under ``tools/*.py`` return a JSON string per
contract (see AGENTS.md "Adding New Tools" — "All handlers MUST return a
JSON string"). Rewriting each of those 100+ call sites to emit TOON
directly would be a huge, error-prone diff for no extra benefit — the
tokens that matter are the ones the *model* reads, and every one of those
JSON strings flows through exactly one place before becoming visible to
the model: the point in ``agent/tool_executor.py`` where a completed
tool's ``function_result`` turns into the appended ``role: "tool"``
message.

This module is that one conversion point. It is intentionally a no-op
unless ``context.toon_prompts`` was pinned on for this session (see
``agent/agent_init.py`` — ``agent._toon_prompts_enabled``, read once at
construction, never re-read mid-conversation for prompt-cache safety).

Call sites that later re-parse a *historical* tool message's content as
JSON (rather than the fresh ``function_result`` from the same turn) need
to understand TOON too — see ``agent.toon_codec.parse_tool_payload`` and
its use in ``agent.tool_result_classification``,
``agent.agent_runtime_helpers.convert_to_trajectory_format``, and
``agent.background_review``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["maybe_toon_encode_tool_result", "TOON_EXEMPT_TOOLS"]


# Tools whose result the model (or a downstream consumer of the raw
# transcript) must be able to treat as literal JSON — e.g. because the
# model is instructed to echo an id/schema fragment back verbatim, or
# because the tool intentionally hands back something that isn't
# JSON-compatible in the first place. TOON round-trips losslessly
# (decode(encode(x)) == x), so this is a conservative allowlist rather
# than a correctness requirement — extend it if a specific tool's
# contract needs the model to see byte-identical JSON.
TOON_EXEMPT_TOOLS = frozenset({
    "todo_write",
    "todo_read",
})


def maybe_toon_encode_tool_result(
    agent: Any,
    tool_name: str,
    function_result: Any,
    *,
    session_id: str = "unknown",
) -> Any:
    """Re-encode a JSON tool-result string as TOON, gated by the pinned flag.

    Returns ``function_result`` unchanged when:
      - the per-session pinned flag (``agent._toon_prompts_enabled``) is off,
      - ``tool_name`` is in ``TOON_EXEMPT_TOOLS`` or the config-extended
        exemption list (``context.toon_exempt_tools``),
      - the result isn't a plain string, or doesn't look like/parse as JSON
        (e.g. already a ``<persisted-output>`` block, plain text, or a
        multimodal content list),
      - TOON encoding itself fails for some unexpected value shape.

    On success, records a token-savings event to the dormant telemetry
    ledger (``agent.telemetry.token_savings``) using the real BPE tokenizer
    when available (``agent.tokens.fast_estimator``).
    """
    if not getattr(agent, "_toon_prompts_enabled", False):
        return function_result
    if not isinstance(function_result, str):
        return function_result
    if tool_name in TOON_EXEMPT_TOOLS or tool_name in _config_exempt_tools(agent):
        return function_result

    text = function_result.strip()
    if not text or text[0] not in "{[":
        # Not JSON-shaped: plain text, an error line, a <persisted-output>
        # block, etc. Nothing to convert.
        return function_result

    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return function_result

    from agent.toon_codec import to_toon

    try:
        encoded = to_toon(payload)
    except Exception:
        logger.debug(
            "toon_boundary: to_toon failed for tool=%s, keeping JSON", tool_name,
            exc_info=True,
        )
        return function_result

    _record_savings(agent, tool_name, text, encoded, session_id)
    return encoded


def _config_exempt_tools(agent: Any) -> frozenset:
    """Optional per-deployment exemption list layered on top of the default.

    ``context.toon_exempt_tools`` in config.yaml, read from the same pinned
    config snapshot the flag itself came from — no extra config read here,
    just an attribute set alongside ``_toon_prompts_enabled`` if present.
    """
    extra = getattr(agent, "_toon_exempt_tools", None)
    if not extra:
        return frozenset()
    return frozenset(extra)


def _record_savings(agent: Any, tool_name: str, raw_text: str, encoded_text: str, session_id: str) -> None:
    """Best-effort telemetry write. Must never affect the caller on failure."""
    try:
        from agent.telemetry.token_savings import record_token_saving
        from agent.tokens.fast_estimator import estimate

        model = getattr(agent, "model", None) or None
        raw_tokens = estimate(raw_text, model=model)
        compressed_tokens = estimate(encoded_text, model=model)
        record_token_saving(
            raw_tokens=raw_tokens,
            compressed_tokens=compressed_tokens,
            tool=tool_name,
            command="tool_executor.boundary",
            adapter=getattr(agent, "provider", None) or "unknown",
            session=session_id or "unknown",
        )
    except Exception:
        logger.debug("toon_boundary: savings telemetry write failed", exc_info=True)
