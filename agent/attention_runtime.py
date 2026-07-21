"""Turn-context adapter for the deterministic attention workspace.

This module only wires the existing attention policy into a real turn.  It does
not execute actions, change the cached system prompt, or persist a second
runtime.  A host may seed ``agent._attention_workspace`` with trusted events;
the adapter selects a goal-scoped, bounded observation delta for the model.
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent.attention_schema import GlobalAttentionWorkspace


ATTENTION_TURN_CONTEXT_SCHEMA = "simplicio.attention-turn-context/v1"
_DEFAULT_BUDGET = 32


def get_attention_workspace(agent: Any) -> GlobalAttentionWorkspace:
    """Return the agent-scoped workspace, creating the safe default lazily."""

    workspace = getattr(agent, "_attention_workspace", None)
    if isinstance(workspace, GlobalAttentionWorkspace):
        return workspace

    workspace = GlobalAttentionWorkspace(budget=_DEFAULT_BUDGET)
    agent._attention_workspace = workspace
    return workspace


def _now(agent: Any) -> int:
    supplied = getattr(agent, "_attention_now", None)
    if callable(supplied):
        supplied = supplied()
    if isinstance(supplied, int) and not isinstance(supplied, bool):
        return supplied
    return int(time.time())


def degraded_attention_context(goal_id: str) -> str:
    """Return an explicit empty safe queue instead of silently omitting state."""

    return json.dumps(
        {
            "schema": ATTENTION_TURN_CONTEXT_SCHEMA,
            "authority": "observation_only",
            "goal_id": goal_id.strip(),
            "degraded": True,
            "workspace": {
                "schema": GlobalAttentionWorkspace.PROMPT_DELTA_SCHEMA,
                "goal_id": goal_id.strip(),
                "degraded": True,
                "items": [],
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def build_attention_turn_context(agent: Any, *, goal_id: str) -> str:
    """Render a bounded attention delta for one model request.

    Empty workspaces do not add noise to the prompt.  Non-empty or degraded
    workspaces include the workspace receipt id as evidence, while causal
    receipts and other private data remain outside the model-facing delta.
    """

    goal_id = goal_id.strip()
    if not goal_id:
        return degraded_attention_context(goal_id)

    try:
        workspace = get_attention_workspace(agent)
        now = _now(agent)
        snapshot = workspace.select(goal_id=goal_id, now=now)
        delta = workspace.prompt_delta(goal_id=goal_id, now=now)
        if not delta["items"] and not delta["degraded"]:
            return ""
        payload = {
            "schema": ATTENTION_TURN_CONTEXT_SCHEMA,
            "authority": "observation_only",
            "goal_id": goal_id,
            "degraded": bool(delta["degraded"]),
            "receipt_id": snapshot.receipt.receipt_id,
            "workspace": delta,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except Exception:
        return degraded_attention_context(goal_id)


__all__ = [
    "ATTENTION_TURN_CONTEXT_SCHEMA",
    "build_attention_turn_context",
    "degraded_attention_context",
    "get_attention_workspace",
]
