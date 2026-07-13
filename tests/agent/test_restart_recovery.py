"""Focused bounded proof for issue #183 restart/effect ambiguity."""

from __future__ import annotations

import pytest

from agent.restart_recovery import (
    EFFECT_RECOVERY_SCHEMA_VERSION,
    EffectJournal,
    EffectState,
    EffectStateConflictError,
    RecoveryDecision,
    EffectRecord,
)
from agent.telemetry.receipts import record_receipt
from agent.task_envelope import TaskEnvelope


def _envelope() -> TaskEnvelope:
    return TaskEnvelope.create(
        repo="simplicio-agent",
        branch="issue-183",
        scope="restart-recovery",
        acceptance_criteria=("committed effects are not retried",),
        task_id="task-183",
        correlation_id="corr-183",
        now_ns=1,
    )


def test_record_round_trip_carries_envelope_and_receipt_hash(tmp_path):
    envelope = _envelope()
    receipt = record_receipt(payload="effect payload", directory=tmp_path / "receipts")
    record = EffectRecord.pending(
        envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2
    ).resolve(EffectState.COMMITTED, receipt=receipt, now_ns=3)

    restored = EffectRecord.from_json(record.to_json())

    assert restored == record
    assert restored.schema_version == EFFECT_RECOVERY_SCHEMA_VERSION
    assert restored.envelope_hash == envelope.content_hash()
    assert restored.receipt_sha == receipt.sha


def test_restart_after_commit_skips_without_retry(tmp_path):
    envelope = _envelope()
    journal_path = tmp_path / "effects.jsonl"
    receipt = record_receipt(payload="committed", directory=tmp_path / "receipts")
    journal = EffectJournal(journal_path)
    journal.begin(envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2)
    journal.resolve(
        envelope,
        effect_id="effect-1",
        idempotency_key="idem-1",
        state=EffectState.COMMITTED,
        receipt=receipt,
        now_ns=3,
    )

    recovered = EffectJournal(journal_path).recover(
        envelope, effect_id="effect-1", idempotency_key="idem-1"
    )

    assert recovered.decision is RecoveryDecision.SKIP_COMMITTED
    assert recovered.should_execute is False
    assert "do not retry" in recovered.reason


def test_not_committed_can_retry_after_restart(tmp_path):
    envelope = _envelope()
    path = tmp_path / "effects.jsonl"
    journal = EffectJournal(path)
    journal.begin(envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2)
    journal.resolve(
        envelope,
        effect_id="effect-1",
        idempotency_key="idem-1",
        state=EffectState.NOT_COMMITTED,
        reason="verifier saw no provider commit",
        now_ns=3,
    )

    recovered = EffectJournal(path).recover(
        envelope, effect_id="effect-1", idempotency_key="idem-1"
    )

    assert recovered.decision is RecoveryDecision.RETRY
    assert recovered.should_execute is True


def test_unknown_is_explicit_and_never_executes(tmp_path):
    envelope = _envelope()
    path = tmp_path / "effects.jsonl"
    journal = EffectJournal(path)
    journal.begin(envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2)
    journal.resolve(
        envelope,
        effect_id="effect-1",
        idempotency_key="idem-1",
        state=EffectState.UNKNOWN,
        reason="process stopped after dispatch before receipt",
        now_ns=3,
    )

    recovered = EffectJournal(path).recover(
        envelope, effect_id="effect-1", idempotency_key="idem-1"
    )

    assert recovered.decision is RecoveryDecision.RECONCILE_UNKNOWN
    assert recovered.observed_state is EffectState.UNKNOWN
    assert recovered.should_execute is False
    assert recovered.reason == "process stopped after dispatch before receipt"


def test_missing_evidence_is_unknown_not_an_implicit_retry(tmp_path):
    recovered = EffectJournal(tmp_path / "missing.jsonl").recover(
        _envelope(), effect_id="effect-1", idempotency_key="idem-1"
    )

    assert recovered.decision is RecoveryDecision.RECONCILE_UNKNOWN
    assert recovered.observed_state is EffectState.UNKNOWN
    assert recovered.should_execute is False
    assert "no durable effect record" in recovered.reason


def test_duplicate_append_is_idempotent(tmp_path):
    envelope = _envelope()
    path = tmp_path / "effects.jsonl"
    journal = EffectJournal(path)
    pending = journal.begin(
        envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2
    )
    journal.append(pending)

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_replayed_begin_and_resolution_do_not_create_new_attempts(tmp_path):
    envelope = _envelope()
    path = tmp_path / "effects.jsonl"
    receipt = record_receipt(payload="committed", directory=tmp_path / "receipts")
    journal = EffectJournal(path)
    pending = journal.begin(
        envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2
    )
    assert journal.begin(
        envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=20
    ) == pending
    committed = journal.resolve(
        envelope,
        effect_id="effect-1",
        idempotency_key="idem-1",
        state=EffectState.COMMITTED,
        receipt=receipt,
        now_ns=3,
    )
    assert journal.resolve(
        envelope,
        effect_id="effect-1",
        idempotency_key="idem-1",
        state=EffectState.COMMITTED,
        receipt=receipt,
        now_ns=30,
    ) == committed
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_committed_cannot_be_downgraded(tmp_path):
    envelope = _envelope()
    path = tmp_path / "effects.jsonl"
    receipt = record_receipt(payload="committed", directory=tmp_path / "receipts")
    journal = EffectJournal(path)
    pending = journal.begin(
        envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2
    )
    committed = journal.append(
        pending.resolve(EffectState.COMMITTED, receipt=receipt, now_ns=3)
    )

    with pytest.raises(EffectStateConflictError, match="cannot be superseded"):
        journal.append(
            committed.resolve(
                EffectState.NOT_COMMITTED,
                reason="stale verifier result",
                now_ns=4,
            )
        )


def test_hash_mismatch_is_explicit_unknown(tmp_path):
    envelope = _envelope()
    path = tmp_path / "effects.jsonl"
    journal = EffectJournal(path)
    journal.begin(envelope, effect_id="effect-1", idempotency_key="idem-1", now_ns=2)
    changed = TaskEnvelope.create(
        repo=envelope.repo,
        branch=envelope.branch,
        scope="different-scope",
        acceptance_criteria=envelope.acceptance_criteria,
        task_id=envelope.task_id,
        correlation_id=envelope.correlation_id,
        now_ns=1,
    )

    recovered = journal.recover(changed, effect_id="effect-1", idempotency_key="idem-1")

    assert recovered.decision is RecoveryDecision.RECONCILE_UNKNOWN
    assert "envelope hash" in recovered.reason
