import pytest

from agent.attention_schema import (
    AcknowledgementState,
    AttentionItem,
    AttentionQueue,
    AttentionReason,
    GlobalAttentionWorkspace,
    WorkspaceSnapshot,
)


def _item(item_id: str, reason: AttentionReason, **changes: object) -> AttentionItem:
    values = {
        "item_id": item_id,
        "source": item_id,
        "reason": reason,
        "expires_at": 100,
        "run_id": "run-a",
        "goal_id": "goal-a",
        "created_at": 0,
        "cause_receipts": (f"receipt-{item_id}",),
    }
    values.update(changes)
    return AttentionItem(**values)  # type: ignore[arg-type]


def test_safety_and_human_gate_preempt_content_controlled_work() -> None:
    queue = AttentionQueue((
        _item("normal", AttentionReason.NORMAL_PROGRESS, relevance=100),
        _item("approval", AttentionReason.APPROVAL, relevance=0),
        _item("safety", AttentionReason.SAFETY, relevance=0),
    ))

    workspace = queue.select_workspace(goal_id="goal-a", budget=2, now=10)

    assert [item.item_id for item in workspace.items] == ["safety", "approval"]
    assert workspace.explain() == (
        "safety: source=safety; run=run-a",
        "approval: source=approval; run=run-a",
    )


def test_selection_is_deterministic_fair_and_priority_is_policy_derived() -> None:
    queue = AttentionQueue((
        _item("new-a", AttentionReason.NORMAL_PROGRESS, created_at=90),
        _item("old-b", AttentionReason.OPTIONAL_LEARNING, run_id="run-b"),
        _item("new-c", AttentionReason.NORMAL_PROGRESS, run_id="run-c"),
    ))

    first = queue.select_workspace(goal_id="goal-a", budget=3, now=100)
    second = queue.select_workspace(goal_id="goal-a", budget=3, now=100)

    assert first == second
    assert {item.run_id for item in first.items} == {"run-a", "run-b", "run-c"}
    assert _item("x", AttentionReason.SAFETY).priority == 0


def test_duplicate_completion_is_published_once_and_open_loop_requires_receipt() -> (
    None
):
    queue = AttentionQueue()
    queue.publish(_item("first", AttentionReason.BACKGROUND_COMPLETED))
    merged = queue.publish(
        _item(
            "duplicate",
            AttentionReason.BACKGROUND_COMPLETED,
            source="first",
            cause_receipts=("receipt-second",),
        )
    )

    assert len(queue.items) == 1
    assert merged.cause_receipts == ("receipt-first", "receipt-second")
    closed = queue.acknowledge(
        "first", AcknowledgementState.COMPLETED, "completion-receipt"
    )
    assert not closed.is_open


def test_workspace_selection_is_goal_scoped_and_emits_a_stable_receipt() -> None:
    queue = AttentionQueue((
        _item(
            "goal-a-item",
            AttentionReason.NORMAL_PROGRESS,
            source="shared-source",
        ),
        _item(
            "goal-b-item",
            AttentionReason.SAFETY,
            goal_id="goal-b",
            source="shared-source",
        ),
    ))

    first = queue.select_workspace(goal_id="goal-a", budget=2, now=10)
    second = queue.select_workspace(goal_id="goal-a", budget=2, now=10)
    other_goal = queue.select_workspace(goal_id="goal-b", budget=2, now=10)

    assert [item.item_id for item in first.items] == ["goal-a-item"]
    assert [item.item_id for item in other_goal.items] == ["goal-b-item"]
    assert first.receipt == second.receipt
    assert first.receipt.receipt_id != other_goal.receipt.receipt_id
    assert first.receipt.to_dict() == {
        "schema": "simplicio.attention-workspace-receipt/v1",
        "receipt_id": first.receipt.receipt_id,
        "goal_id": "goal-a",
        "selected_at": 10,
        "budget": 2,
        "used": 1,
        "item_ids": ["goal-a-item"],
    }


def test_global_workspace_has_fixed_budget_and_safe_prompt_delta() -> None:
    workspace = GlobalAttentionWorkspace(budget=2)
    workspace.publish(
        _item(
            "approval",
            AttentionReason.APPROVAL,
            cause_receipts=("receipt", "private reasoning must not leak"),
            profile_id="profile-a",
        )
    )

    first = workspace.prompt_delta(goal_id="goal-a", now=10)
    second = workspace.prompt_delta(goal_id="goal-a", now=10)

    assert first == second
    assert first == {
        "schema": "simplicio.attention-prompt-delta/v1",
        "goal_id": "goal-a",
        "degraded": False,
        "items": [{
            "item_id": "approval",
            "source": "approval",
            "reason": "approval",
            "run": "run-a",
            "profile": "profile-a",
            "status": "open",
        }],
    }
    assert "private reasoning" not in str(first)


def test_expired_items_are_ignored_and_old_work_cannot_starve() -> None:
    queue = AttentionQueue((
        _item("expired", AttentionReason.SAFETY, expires_at=5),
        _item("normal", AttentionReason.NORMAL_PROGRESS, created_at=90),
        _item(
            "old-learning",
            AttentionReason.OPTIONAL_LEARNING,
            created_at=-1000,
            run_id="run-b",
        ),
    ))

    snapshot = queue.select_workspace(goal_id="goal-a", budget=1, now=100)

    assert [item.item_id for item in snapshot.items] == ["old-learning"]


def test_global_workspace_degrades_to_preemptive_safe_queue() -> None:
    workspace = GlobalAttentionWorkspace(budget=3)
    workspace.publish(_item("approval", AttentionReason.APPROVAL))
    workspace.publish(_item("normal", AttentionReason.NORMAL_PROGRESS))

    def fail_selection(**_: object) -> WorkspaceSnapshot:
        raise RuntimeError("workspace unavailable")

    workspace.queue.select_workspace = fail_selection  # type: ignore[method-assign]
    snapshot = workspace.select(goal_id="goal-a", now=10)

    assert snapshot.degraded is True
    assert [item.item_id for item in snapshot.items] == ["approval"]


def test_priority_is_policy_derived_and_not_an_untrusted_constructor_field() -> None:
    with pytest.raises(TypeError):
        AttentionItem(  # type: ignore[call-arg]
            item_id="x",
            source="x",
            reason=AttentionReason.NORMAL_PROGRESS,
            expires_at=10,
            run_id="run-a",
            goal_id="goal-a",
            created_at=0,
            priority=0,
        )
