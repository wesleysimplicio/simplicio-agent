import pytest

from agent.event_store import ExecutionContext, RunEvent


def test_execution_context_and_event_have_canonical_hashes():
    context = ExecutionContext(
        profile_id="profile-1",
        tenant_id="tenant-1",
        session_id="session-1",
        run_id="run-1",
        goal_hash="goal-sha",
        anchor_hash="anchor-sha",
        phase="observe",
        step=2,
    )
    event = RunEvent(
        event_id="event-1",
        run_id=context.run_id,
        causal_parent=None,
        sequence=1,
        idempotency_key="run-1:1",
        event_type="run.started",
        actor="agent",
        source="cli",
        payload_ref="payload:1",
        classification="canon",
    )

    assert context.to_dict()["schema"] == "simplicio.execution-context/v1"
    assert len(context.content_hash()) == 64
    assert event.to_dict()["schema"] == "simplicio.run-event/v1"
    assert len(event.content_hash()) == 64


def test_run_event_rejects_non_positive_sequence():
    with pytest.raises(ValueError, match="sequence"):
        RunEvent("e", "r", None, 0, "key", "type", "actor", "source", "ref", "canon")
