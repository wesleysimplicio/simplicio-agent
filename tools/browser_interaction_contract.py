"""Shared browser interaction routing and compact browser-state helpers.

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

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
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

_DEFAULT_STATE_BUDGET = 2400
_GENERATIONAL_REF = re.compile(r"^@g(?P<generation>[1-9][0-9]*)-(?P<ref>e[0-9]+)$")
_ACTIONABLE_ROLES = frozenset(
    {
        "button",
        "checkbox",
        "combobox",
        "link",
        "menuitem",
        "option",
        "radio",
        "searchbox",
        "slider",
        "spinbutton",
        "tab",
        "textbox",
    }
)


def _redact(value: Any) -> Any:
    """Redact browser content before it reaches the sidecar or prompt."""
    from agent.redact import redact_sensitive_text

    if isinstance(value, str):
        return redact_sensitive_text(value, force=True)
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _state_root() -> Path:
    configured = os.getenv("HERMES_BROWSER_STATE_DIR", "").strip()
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "hermes-browser-state"


def _budget() -> int:
    try:
        return max(256, int(os.getenv("HERMES_BROWSER_STATE_MAX_CHARS", _DEFAULT_STATE_BUDGET)))
    except (TypeError, ValueError):
        return _DEFAULT_STATE_BUDGET


def vision_escalation_reason(
    snapshot: str,
    *,
    explicit_request: bool = False,
) -> Optional[str]:
    """Return a bounded, evidence-based reason to request visual fallback."""
    if explicit_request:
        return "explicit_request"
    normalized = str(snapshot or "").lower()
    if "<canvas" in normalized or " canvas " in f" {normalized} ":
        return "canvas"
    if "image-only" in normalized or "visual verification" in normalized:
        return "image_only_control"
    if not normalized.strip() or not any(f" {role} " in f" {normalized} " for role in _ACTIONABLE_ROLES):
        return "inaccessible_accessibility"
    return None


class BrowserStateRegistry:
    """Keep the full redacted snapshot external and expose a bounded projection."""

    def __init__(self) -> None:
        self._states: Dict[str, Dict[str, Any]] = {}

    def capture(
        self,
        task_id: str,
        snapshot: str,
        refs: Optional[Mapping[str, Any]] = None,
        *,
        url: str = "",
        title: str = "",
        focused: str = "",
    ) -> Dict[str, Any]:
        previous = self._states.get(task_id)
        generation = int(previous["generation"]) + 1 if previous else 1
        safe_snapshot = _redact(str(snapshot or ""))
        safe_refs = _redact(dict(refs or {}))
        payload = {
            "generation": generation,
            "snapshot": safe_snapshot,
            "refs": safe_refs,
            "url": _redact(url),
            "title": _redact(title),
            "focused": _redact(focused),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        root = _state_root()
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{digest}.json").write_text(
            json.dumps(payload, sort_keys=True, ensure_ascii=False), encoding="utf-8"
        )

        actions = []
        raw_refs: Dict[str, str] = {}
        for raw_ref, metadata in sorted(safe_refs.items(), key=lambda item: str(item[0])):
            raw = str(raw_ref)
            raw = raw if raw.startswith("@") else f"@{raw}"
            if not re.fullmatch(r"@e[0-9]+", raw):
                continue
            public_ref = f"@g{generation}-{raw[1:]}"
            raw_refs[public_ref] = raw
            metadata = metadata if isinstance(metadata, Mapping) else {}
            role = str(metadata.get("role") or "").lower()
            if role and role not in _ACTIONABLE_ROLES:
                continue
            actions.append(
                {
                    "id": public_ref,
                    "role": role,
                    "name": str(metadata.get("name") or ""),
                }
            )
        actions.sort(key=lambda item: (item["role"], item["name"], item["id"]))

        compact_text = "\n".join(
            line.strip() for line in safe_snapshot.splitlines() if line.strip()
        )
        compact_text = compact_text[:_budget()]
        state = {
            "generation": generation,
            "snapshot_ref": f"browser://snapshot/{digest}",
            "snapshot_bytes": len(safe_snapshot.encode("utf-8")),
            "token_budget": _budget() // 4,
            "node_count": len(safe_refs),
            "actions": actions,
            "text": compact_text,
            "vision_escalation": {
                "required": vision_escalation_reason(safe_snapshot) is not None,
                "reason": vision_escalation_reason(safe_snapshot),
                "max_description_chars": 600,
            },
        }
        self._states[task_id] = {"generation": generation, "refs": raw_refs}
        return state

    def resolve(self, task_id: str, ref: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve a public ref, rejecting stale generation-bound ids."""
        state = self._states.get(task_id)
        if state is None:
            return ref, None
        match = _GENERATIONAL_REF.fullmatch(ref)
        if not match:
            return ref, None
        generation = int(match.group("generation"))
        if generation != state["generation"]:
            return None, "stale browser reference; refresh browser_snapshot"
        resolved = state["refs"].get(ref)
        if resolved is None:
            return None, "unknown browser reference; refresh browser_snapshot"
        return resolved, None

    def has_state(self, task_id: str) -> bool:
        return task_id in self._states


_BROWSER_STATE_REGISTRY = BrowserStateRegistry()


def register_browser_snapshot(
    task_id: str,
    snapshot: str,
    refs: Optional[Mapping[str, Any]] = None,
    **metadata: str,
) -> Dict[str, Any]:
    return _BROWSER_STATE_REGISTRY.capture(task_id, snapshot, refs, **metadata)


def resolve_browser_ref(task_id: str, ref: str) -> tuple[Optional[str], Optional[str]]:
    return _BROWSER_STATE_REGISTRY.resolve(task_id, ref)


def browser_state_exists(task_id: str) -> bool:
    return _BROWSER_STATE_REGISTRY.has_state(task_id)


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
    "browser_state_exists",
    "register_browser_snapshot",
    "resolve_browser_ref",
    "vision_escalation_reason",
]
