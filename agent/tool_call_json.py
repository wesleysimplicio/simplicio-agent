"""Fast, compatibility-preserving JSON helpers for OpenAI-style tool calls.

Tool-call arguments are decoded once per tool invocation and while assembling
streamed calls.  The repository already has an optional orjson fast path with
a stdlib fallback; this module centralizes its use instead of making each
caller handle backend-specific exception types.
"""

from __future__ import annotations

import json
from typing import Any

from agent._fastjson import dumps as _fast_dumps
from agent._fastjson import loads as _fast_loads


def loads_tool_call_arguments(raw: Any) -> Any:
    """Decode tool-call JSON using the optional fast path.

    If the optional backend rejects a value (for example, a stdlib-compatible
    edge case such as ``NaN`` or a lone surrogate), retry with stdlib JSON.
    When both decoders reject malformed input, the stdlib exception is allowed
    to escape so existing ``json.JSONDecodeError`` handling remains unchanged.
    """

    try:
        return _fast_loads(raw)
    except Exception:
        # Keep stdlib's public exception and permissive compatibility contract
        # at the boundary.  This is a fallback, not a second successful parse
        # for the normal valid-JSON hot path.
        return json.loads(raw)


def parse_tool_call_arguments(raw: Any) -> dict[str, Any]:
    """Decode tool-call arguments and normalize non-object JSON to ``{}``.

    This matches the agent loop's existing behavior: a tool's arguments must
    be an object before middleware or dispatch sees them.
    """

    parsed = loads_tool_call_arguments(raw)
    return parsed if isinstance(parsed, dict) else {}


def dumps_tool_call_arguments(value: Any, *, sort_keys: bool = False) -> str:
    """Serialize JSON-compatible tool arguments as compact UTF-8 text.

    ``_fastjson.dumps`` uses orjson when installed and already falls back to
    stdlib when it is not.  The local ``except`` is an additional guard for
    backend-specific serialization errors and preserves the same output
    contract without making the optional dependency mandatory.
    """

    try:
        return _fast_dumps(
            value,
            ensure_ascii=False,
            sort_keys=sort_keys,
            separators=(",", ":"),
        )
    except Exception:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=sort_keys,
            separators=(",", ":"),
        )


__all__ = [
    "dumps_tool_call_arguments",
    "loads_tool_call_arguments",
    "parse_tool_call_arguments",
]
