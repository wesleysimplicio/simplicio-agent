"""Bounded gateway restart/effect continuity proof for issue #183."""

import json
import asyncio
from types import SimpleNamespace

import pytest

from gateway.restart import (
    EffectState,
    RecoveryDecision,
    RestartEffectConflictError,
    RestartEffectJournal,
    is_stale_restart_redelivery,
)
from gateway.config import GatewayConfig, Platform
from gateway.delivery import DeliveryRouter, DeliveryTarget
from gateway.platforms.base import SendResult


def test_committed_effect_is_skipped_after_fresh_journal_load(tmp_path):
    path = tmp_path / "restart-effects.jsonl"
    journal = RestartEffectJournal(path)
    journal.begin(
        effect_id="send-1",
        idempotency_key="idem-1",
        task_id="task-183",
        correlation_id="corr-183",
        now_ns=1,
    )
    journal.resolve(
        effect_id="send-1",
        idempotency_key="idem-1",
        state=EffectState.COMMITTED,
        receipt="message-1",
        now_ns=2,
    )

    recovered = RestartEffectJournal(path).recover(
        effect_id="send-1",
        idempotency_key="idem-1",
        task_id="task-183",
        correlation_id="corr-183",
    )

    assert recovered.decision is RecoveryDecision.SKIP_COMMITTED
    assert recovered.should_execute is False
    assert recovered.record.receipt == "message-1"


def test_not_committed_is_the_only_restart_retry_decision(tmp_path):
    journal = RestartEffectJournal(tmp_path / "effects.jsonl")
    journal.begin(effect_id="send-1", idempotency_key="idem-1", now_ns=1)
    journal.resolve(
        effect_id="send-1",
        idempotency_key="idem-1",
        state=EffectState.NOT_COMMITTED,
        reason="provider confirmed no commit",
        now_ns=2,
    )

    recovered = RestartEffectJournal(journal.path).recover(
        effect_id="send-1", idempotency_key="idem-1"
    )

    assert recovered.decision is RecoveryDecision.RETRY
    assert recovered.should_execute is True


@pytest.mark.parametrize("state", [EffectState.PENDING, EffectState.UNKNOWN])
def test_pending_and_unknown_never_execute(tmp_path, state):
    journal = RestartEffectJournal(tmp_path / f"{state.value}.jsonl")
    journal.begin(effect_id="send-1", idempotency_key="idem-1", now_ns=1)
    if state is EffectState.UNKNOWN:
        journal.resolve(
            effect_id="send-1",
            idempotency_key="idem-1",
            state=state,
            reason="process stopped after dispatch",
            now_ns=2,
        )

    recovered = RestartEffectJournal(journal.path).recover(
        effect_id="send-1", idempotency_key="idem-1"
    )

    assert recovered.decision is RecoveryDecision.RECONCILE_UNKNOWN
    assert recovered.should_execute is False


def test_causal_identity_mismatch_is_unknown_not_retry(tmp_path):
    journal = RestartEffectJournal(tmp_path / "effects.jsonl")
    journal.begin(
        effect_id="send-1",
        idempotency_key="idem-1",
        task_id="task-183",
        correlation_id="corr-183",
        now_ns=1,
    )
    journal.resolve(
        effect_id="send-1",
        idempotency_key="idem-1",
        state=EffectState.NOT_COMMITTED,
        reason="no provider commit",
        now_ns=2,
    )

    recovered = RestartEffectJournal(journal.path).recover(
        effect_id="send-1",
        idempotency_key="idem-1",
        task_id="other-task",
        correlation_id="corr-183",
    )

    assert recovered.decision is RecoveryDecision.RECONCILE_UNKNOWN
    assert recovered.should_execute is False


def test_replayed_begin_and_resolution_do_not_append_duplicates(tmp_path):
    path = tmp_path / "effects.jsonl"
    journal = RestartEffectJournal(path)
    pending = journal.begin(effect_id="send-1", idempotency_key="idem-1", now_ns=1)
    assert journal.begin(effect_id="send-1", idempotency_key="idem-1", now_ns=3) == pending
    committed = journal.resolve(
        effect_id="send-1",
        idempotency_key="idem-1",
        state=EffectState.COMMITTED,
        receipt="message-1",
        now_ns=2,
    )
    assert journal.resolve(
        effect_id="send-1",
        idempotency_key="idem-1",
        state=EffectState.COMMITTED,
        receipt="message-1",
        now_ns=4,
    ) == committed
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_committed_effect_cannot_be_downgraded(tmp_path):
    journal = RestartEffectJournal(tmp_path / "effects.jsonl")
    journal.begin(effect_id="send-1", idempotency_key="idem-1", now_ns=1)
    journal.resolve(
        effect_id="send-1",
        idempotency_key="idem-1",
        state=EffectState.COMMITTED,
        receipt="message-1",
        now_ns=2,
    )

    with pytest.raises(RestartEffectConflictError, match="downgraded"):
        journal.resolve(
            effect_id="send-1",
            idempotency_key="idem-1",
            state=EffectState.NOT_COMMITTED,
            reason="stale observation",
            now_ns=3,
        )


def _restart_event(update_id):
    return SimpleNamespace(
        platform_update_id=update_id,
        source=SimpleNamespace(platform=SimpleNamespace(value="telegram")),
    )


def test_redelivery_marker_is_bounded_and_platform_specific(tmp_path):
    marker = tmp_path / ".restart_last_processed.json"
    marker.write_text(
        json.dumps({"platform": "telegram", "update_id": 100, "requested_at": 90.0}),
        encoding="utf-8",
    )

    assert is_stale_restart_redelivery(_restart_event(100), marker, now=100.0)
    assert is_stale_restart_redelivery(_restart_event(99), marker, now=100.0)
    assert not is_stale_restart_redelivery(_restart_event(101), marker, now=100.0)
    assert not is_stale_restart_redelivery(_restart_event(100), marker, now=401.0)
    assert not is_stale_restart_redelivery(_restart_event(None), marker, now=100.0)


def test_missing_effect_record_is_explicit_unknown(tmp_path):
    recovered = RestartEffectJournal(tmp_path / "missing.jsonl").recover(
        effect_id="send-1", idempotency_key="idem-1"
    )

    assert recovered.observed_state is EffectState.UNKNOWN
    assert recovered.decision is RecoveryDecision.RECONCILE_UNKNOWN
    assert recovered.should_execute is False


class _Adapter:
    splits_long_messages = False

    def __init__(self, result=None, error=None):
        self.result = result or SendResult(success=True, message_id="message-1")
        self.error = error
        self.calls = 0

    async def send(self, chat_id, content, metadata=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def _target():
    return DeliveryTarget(platform=Platform.TELEGRAM, chat_id="chat-1")


def _metadata():
    return {
        "effect_id": "send-1",
        "idempotency_key": "idem-1",
        "task_id": "task-183",
        "correlation_id": "corr-183",
    }


def test_delivery_does_not_repeat_committed_effect_after_restart(tmp_path):
    async def run():
        path = tmp_path / "effects.jsonl"
        first_adapter = _Adapter()
        first = DeliveryRouter(
            GatewayConfig(),
            adapters={Platform.TELEGRAM: first_adapter},
            effect_journal=RestartEffectJournal(path),
        )
        first_result = await first.deliver("hello", [_target()], metadata=_metadata())
        assert first_result["telegram:chat-1"]["success"], first_result

        second_adapter = _Adapter()
        second = DeliveryRouter(
            GatewayConfig(),
            adapters={Platform.TELEGRAM: second_adapter},
            effect_journal=RestartEffectJournal(path),
        )
        result = await second.deliver("hello", [_target()], metadata=_metadata())

        assert result["telegram:chat-1"]["skipped"] == "committed_effect"
        assert second_adapter.calls == 0

    asyncio.run(run())


def test_ambiguous_delivery_failure_is_unknown_and_not_retried(tmp_path):
    async def run():
        path = tmp_path / "effects.jsonl"
        first_adapter = _Adapter(error=TimeoutError("response lost after dispatch"))
        first = DeliveryRouter(
            GatewayConfig(),
            adapters={Platform.TELEGRAM: first_adapter},
            effect_journal=RestartEffectJournal(path),
        )
        first_result = await first.deliver("hello", [_target()], metadata=_metadata())
        assert first_result["telegram:chat-1"]["effect_unknown"] is True

        second_adapter = _Adapter()
        second = DeliveryRouter(
            GatewayConfig(),
            adapters={Platform.TELEGRAM: second_adapter},
            effect_journal=RestartEffectJournal(path),
        )
        second_result = await second.deliver("hello", [_target()], metadata=_metadata())

        assert second_result["telegram:chat-1"]["effect_unknown"] is True
        assert second_adapter.calls == 0

    asyncio.run(run())
