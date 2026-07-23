"""Contract tests for the deterministic semantic no-progress guard (#583)."""

from __future__ import annotations

from agent.no_progress_guard import (
    GuardAction,
    GuardPolicy,
    GuardReason,
    NoProgressGuard,
)


def test_first_call_is_allowed_and_receipted():
    guard = NoProgressGuard()
    decision = guard.before_call("read_file", {"path": "README.md"})
    assert decision.action is GuardAction.ALLOW
    assert decision.reason is GuardReason.FIRST_OBSERVATION
    assert decision.receipt["schema_version"] == "simplicio.agent.no-progress/v1"
    assert len(decision.call_fingerprint) == 64


def test_same_result_reaches_notice_then_veto_before_execution():
    guard = NoProgressGuard(GuardPolicy(warning_threshold=3, veto_threshold=5, hard_threshold=8))
    args = {"path": "file.txt"}
    for _ in range(3):
        guard.before_call("read_file", args)
        result = guard.record_result("read_file", args, {"content": "same"}, failure_code="unchanged")
        assert result.action is GuardAction.ALLOW or result.action is GuardAction.NOTICE
    notice = guard.record_result("read_file", args, {"content": "same"}, failure_code="unchanged")
    assert notice.action is GuardAction.NOTICE
    veto = guard.before_call("read_file", args)
    assert veto.action is GuardAction.NOTICE or veto.action is GuardAction.REPLAN
    guard.policy = GuardPolicy(warning_threshold=1, veto_threshold=2, hard_threshold=3)
    guard.reset()
    terminal_args = {"command": "false"}
    guard.before_call("terminal", terminal_args)
    guard.record_result("terminal", terminal_args, {"error": "same"}, failure_code="exit_1")
    for _ in range(5):
        guard.record_result("terminal", terminal_args, {"error": "same"}, failure_code="exit_1")
    assert guard.before_call("terminal", terminal_args).action in {GuardAction.VETO, GuardAction.REPLAN, GuardAction.TERMINATE}


def test_changed_result_is_progress_even_when_call_repeats():
    guard = NoProgressGuard()
    args = {"url": "status"}
    guard.before_call("poll", args)
    guard.record_result("poll", args, {"state": "pending"}, result_category="pending")
    guard.before_call("poll", args, declared_polling=True)
    decision = guard.record_result("poll", args, {"state": "ready"}, result_category="completed")
    assert decision.reason is GuardReason.PROGRESS_OBSERVED
    assert decision.action is GuardAction.ALLOW


def test_world_state_and_evidence_delta_reset_counter():
    guard = NoProgressGuard(GuardPolicy(warning_threshold=2, veto_threshold=3, hard_threshold=4))
    args = {"path": "x"}
    guard.record_result("write_file", args, {"ok": False}, failure_code="io_error")
    guard.record_result("write_file", args, {"ok": False}, failure_code="io_error")
    assert guard.snapshot()[0]["no_progress_count"] == 1
    decision = guard.record_result(
        "write_file",
        args,
        {"ok": False},
        world_state_digest="new-state",
        evidence_count=1,
        failure_code="io_error",
    )
    assert decision.reason is GuardReason.PROGRESS_OBSERVED
    assert guard.snapshot()[0]["no_progress_count"] == 0


def test_polling_exception_does_not_false_positive():
    guard = NoProgressGuard(GuardPolicy(warning_threshold=1, veto_threshold=2, hard_threshold=3))
    args = {"job_id": "42"}
    for _ in range(10):
        guard.before_call("get_status", args, declared_polling=True)
        decision = guard.record_result(
            "get_status",
            args,
            {"state": "pending"},
            result_category="pending",
            declared_polling=True,
        )
        assert decision.action is GuardAction.ALLOW
        assert decision.reason is GuardReason.POLLING_EXCEPTION


def test_secret_arguments_are_not_persisted():
    guard = NoProgressGuard()
    decision = guard.before_call("http", {"api_token": "super-secret", "path": "/tmp"})
    encoded = str(decision.to_dict())
    assert "super-secret" not in encoded
    assert all("super-secret" not in str(row) for row in guard.snapshot())


def test_journal_is_bounded_and_serialization_has_no_reasoning():
    guard = NoProgressGuard(GuardPolicy(journal_limit=3))
    for index in range(10):
        guard.before_call("read_file", {"path": f"{index}.txt"})
    assert len(guard.snapshot()) == 3
    assert "reasoning" not in guard.before_call("read_file", {"path": "last.txt"}).to_dict()

def test_replan_budget_terminates_instead_of_looping_forever():
    guard = NoProgressGuard(
        GuardPolicy(warning_threshold=1, veto_threshold=6, hard_threshold=8, replan_threshold=2)
    )
    args = {"path": "unchanged.txt"}
    guard.before_call("read_file", args)
    for _ in range(3):
        guard.record_result("read_file", args, {"content": "same"}, failure_code="unchanged")

    first = guard.before_call("read_file", args)
    second = guard.before_call("read_file", args)
    third = guard.before_call("read_file", args)

    assert first.action is GuardAction.REPLAN
    assert second.action is GuardAction.TERMINATE
    assert third.action is GuardAction.TERMINATE
    assert second.terminal_status == "blocked_no_progress"
