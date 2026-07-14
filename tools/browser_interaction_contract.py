"""Shared browser interaction routing and receipt helpers.

This module keeps the browser/computer-use adapter contract deterministic and
small:

* browser provider setup metadata advertises DOM/CDP-first routing with a
  visual fallback reason;
* capture-style tool receipts spell out which route won and whether the result
  was read-only;
* the same helper can be reused by browser and computer-use adapters without
  introducing a new transport layer.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

BROWSER_INTERACTION_OPERATIONS = (
    "navigate",
    "snapshot",
    "dom",
    "a11y",
    "click",
    "type",
    "select",
    "upload",
    "download",
    "tabs",
    "console",
    "network",
    "screenshot",
    "close",
)

COMPUTER_USE_INTERACTION_OPERATIONS = (
    "capture",
    "click",
    "type",
    "key",
    "scroll",
    "drag",
    "list_apps",
    "focus_app",
    "set_value",
    "wait",
    "recording",
    "cancel",
    "health",
)

_VISUAL_FALLBACK_REASON = (
    "Use visual fallback only when DOM/CDP or accessibility data cannot "
    "represent the interaction."
)


def browser_provider_capabilities() -> Dict[str, Any]:
    """Return the shared browser provider capability metadata."""
    return {
        "routing": {
            "primary": "dom/cdp",
            "fallback": "visual",
            "fallback_reason": _VISUAL_FALLBACK_REASON,
        },
        "operations": list(BROWSER_INTERACTION_OPERATIONS),
        "safety": {
            "no_effect": ["snapshot", "console"],
            "effectful": [
                op
                for op in BROWSER_INTERACTION_OPERATIONS
                if op not in {"snapshot", "console"}
            ],
        },
    }


def browser_interaction_receipt(
    *,
    surface: str,
    selection: str,
    effect: str = "read_only",
    fallback_reason: str = "",
    details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a compact receipt for read-only browser/computer-use captures."""
    receipt: Dict[str, Any] = {
        "surface": surface,
        "selection": selection,
        "effect": effect,
        "no_effect": effect == "read_only",
    }
    if fallback_reason:
        receipt["fallback_reason"] = fallback_reason
    if details:
        receipt["details"] = dict(details)
    return receipt


__all__ = [
    "BROWSER_INTERACTION_OPERATIONS",
    "COMPUTER_USE_INTERACTION_OPERATIONS",
    "browser_interaction_receipt",
    "browser_provider_capabilities",
]
