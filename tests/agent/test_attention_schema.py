from agent.attention_schema import (
    AcknowledgementState,
    AttentionItem,
    AttentionQueue,
    AttentionReason,
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
