from __future__ import annotations

import json

from agent.attention_runtime import (
    ATTENTION_TURN_CONTEXT_SCHEMA,
    build_attention_turn_context,
    degraded_attention_context,
    get_attention_workspace,
)
from agent.attention_schema import AttentionItem, AttentionReason


class _Agent:
    _attention_now = 10


def _approval() -> AttentionItem:
    return AttentionItem(
        item_id="approval-1",
        source="human-gate",
        reason=AttentionReason.APPROVAL,
        expires_at=100,
        run_id="run-a",
        goal_id="goal-a",
        created_at=0,
        cause_receipts=("gate-receipt",),
    )


def test_turn_delta_is_goal_scoped_and_carries_workspace_evidence():
    agent = _Agent()
    get_attention_workspace(agent).publish(_approval())

    payload = json.loads(build_attention_turn_context(agent, goal_id="goal-a"))

    assert payload["schema"] == ATTENTION_TURN_CONTEXT_SCHEMA
    assert payload["authority"] == "observation_only"
    assert payload["workspace"]["items"][0]["reason"] == "approval"
    assert payload["workspace"]["items"][0]["status"] == "open"
    assert payload["receipt_id"]
    assert "gate-receipt" not in json.dumps(payload)


def test_empty_goal_uses_explicit_safe_queue():
    payload = json.loads(degraded_attention_context("  "))

    assert payload["degraded"] is True
    assert payload["workspace"]["items"] == []


def test_empty_workspace_does_not_add_turn_noise():
    assert build_attention_turn_context(_Agent(), goal_id="goal-a") == ""
