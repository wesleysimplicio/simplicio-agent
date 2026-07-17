"""Timing benchmark for AttentionQueue.select_workspace.

This is a narrow, honest slice of the benchmark the issue asks for
(missed-critical-event, context tokens, attention latency, task success).
It measures wall-clock latency of workspace selection under a realistic
item count so a future regression in selection cost is caught. It does
NOT measure missed-critical-event rate, context-token delta, or task
success -- those require an integrated runtime harness that does not
exist for this module yet.
"""

import time

from agent.attention_schema import (
    AttentionItem,
    AttentionQueue,
    AttentionReason,
)


def _build_queue(n: int) -> AttentionQueue:
    items = [
        AttentionItem(
            item_id=f"item-{i}",
            source=f"source-{i}",
            reason=AttentionReason.NORMAL_PROGRESS if i % 5 else AttentionReason.SAFETY,
            expires_at=10_000,
            run_id=f"run-{i % 10}",
            goal_id="goal-a",
            created_at=0,
            relevance=i % 100,
        )
        for i in range(n)
    ]
    return AttentionQueue(items)


def test_select_workspace_latency_scales_reasonably_with_queue_size():
    """Real timing measurement: selection over 2000 items must stay fast.

    This is a coarse regression guard, not a formal statistical benchmark:
    it fails only if selection becomes pathologically slow (e.g. an
    accidental O(n^2) blowup), well above normal machine-noise variance.
    """

    queue = _build_queue(2000)

    start = time.perf_counter()
    snapshot = queue.select_workspace(goal_id="goal-a", budget=32, now=5000)
    elapsed = time.perf_counter() - start

    assert len(snapshot.items) <= 32
    assert elapsed < 2.0, f"select_workspace took {elapsed:.3f}s for 2000 items"
