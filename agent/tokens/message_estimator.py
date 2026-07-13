"""Message-list token estimator that delegates text counting to
``agent.tokens.fast_estimator`` (tiktoken when installed, else the exact
same ``len // 4`` naive formula used by ``agent.model_metadata``'s
existing estimator) — issue #111.

Image-token-cost semantics are preserved EXACTLY from
``agent.model_metadata.estimate_messages_tokens_rough``: this module reuses
its private image-counting helpers rather than reimplementing them, so a
screenshot is always ~1500 tokens regardless of which text backend is
active. See ``tests/agent/tokens/test_message_estimator.py`` for the
byte-for-byte equivalence test that pins this.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.model_metadata import _count_image_tokens
from agent.tokens.fast_estimator import estimate as _estimate_text

_IMAGE_TOKEN_COST = 1500


def _message_text_parts(msg: Dict[str, Any]) -> List[str]:
    """Extract the text-bearing substrings of a message, mirroring
    ``agent._hermes_fast._py_message_cost``'s traversal (role + content,
    including nested list/dict content parts) but WITHOUT re-serializing
    non-string values through JSON — those are token-estimated as their
    ``str()`` representation instead, consistent with how the rest of this
    module treats non-text payloads (deterministic, cheap, no import of the
    JSON layer needed just to estimate a token count).
    """
    parts: List[str] = []
    role = msg.get("role") if isinstance(msg, dict) else None
    if isinstance(role, str):
        parts.append(role)

    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # Image parts are counted ONLY via _count_image_tokens (the
                # flat per-image cost) — never re-stringified as text here,
                # or the base64 payload would be double-counted as both an
                # image AND a wall of text.
                if item.get("type") in {"image", "image_url", "input_image"}:
                    continue
                for v in item.values():
                    if isinstance(v, str):
                        parts.append(v)
                    elif v is not None:
                        parts.append(str(v))
            elif item is not None:
                parts.append(str(item))
    elif content is not None and not isinstance(content, dict):
        parts.append(str(content))
    return parts


def estimate_messages_tokens_fast(messages: List[Dict[str, Any]], *, model: str | None = None) -> int:
    """Token estimate for a message list, text via ``fast_estimator``.

    Image parts are counted identically to
    ``estimate_messages_tokens_rough`` (flat ``_IMAGE_TOKEN_COST`` per
    image, not raw base64 length) — this is the AC's "image-token-cost
    semantics preserved exactly" requirement.
    """
    total = 0
    for msg in messages:
        if not isinstance(msg, dict):
            total += _estimate_text(str(msg), model=model)
            continue
        for part in _message_text_parts(msg):
            total += _estimate_text(part, model=model)
        total += _count_image_tokens(msg, _IMAGE_TOKEN_COST)
    return total
