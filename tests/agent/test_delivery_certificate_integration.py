import pytest

from agent.task_envelope import CloseGateError, TaskEnvelope, TaskLedger, TaskState
from agent.turn_envelope import _turn_delivery_certificate


def _delivered_envelope(task_id: str = "turn-integration") -> TaskEnvelope:
    envelope = TaskEnvelope.create(
        repo="repo",
        branch="codex/issue-24",
        scope="delivery certificate",
        acceptance_criteria=("certificate required",),
        task_id=task_id,
        now_ns=1,
    )
    envelope = envelope.transition(TaskState.ORIENTED, now_ns=2)
    envelope = envelope.transition(TaskState.PLANNED, now_ns=3)
    envelope = envelope.transition(TaskState.CLAIMED, now_ns=4)
    envelope = envelope.transition(TaskState.EXECUTING, now_ns=5)
    envelope = envelope.transition(TaskState.VALIDATING, now_ns=6)
    envelope = envelope.transition(
        TaskState.EVIDENCE_READY,
        evidence_refs=(f"turn:{task_id}",),
        receipts=(f"turn:{task_id}",),
        now_ns=7,
    )
    return envelope.transition(
        TaskState.DELIVERED,
        delivery_target="chat-response",
        now_ns=8,
    )


def test_close_requires_and_attaches_verified_delivery_certificate():
    envelope = _delivered_envelope()
    ledger = TaskLedger()
    certificate = _turn_delivery_certificate(
        envelope.task_id, f"turn:{envelope.task_id}"
    )

    closed = ledger.close_with_certificate(
        envelope,
        delivery_certificate=certificate,
        verified_evidence_refs=(f"turn:{envelope.task_id}",),
    )

    assert closed.state is TaskState.CLOSED
    assert ledger.delivery_certificate(envelope.task_id) == certificate.to_dict()
    assert (
        TaskLedger.from_snapshot(ledger.snapshot()).delivery_certificate(
            envelope.task_id
        )
        == certificate.to_dict()
    )


def test_close_quarantines_mismatched_certificate():
    envelope = _delivered_envelope()
    ledger = TaskLedger()
    certificate = _turn_delivery_certificate(
        envelope.task_id, f"turn:{envelope.task_id}"
    )
    mismatched = certificate.to_dict()
    mismatched["task_id"] = "another-task"

    with pytest.raises(CloseGateError) as error:
        ledger.close_with_certificate(
            envelope,
            delivery_certificate=mismatched,
            verified_evidence_refs=(f"turn:{envelope.task_id}",),
        )

    assert error.value.decision.reason_code.value == "delivery_certificate_invalid"
    assert ledger.quarantine_history(envelope.task_id)
