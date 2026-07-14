"""Focused tests for the live-commit/pending-manual-pull boundary."""

from tools.live_commit_attestation import (
    AttestationStatus,
    CodeIdentity,
    PullStatus,
    attest_live_commit,
    attest_rollback,
    detect_manual_pull,
    loaded_code_digest,
)


OLD = CodeIdentity("a" * 40, "sha256:" + "1" * 64)
NEW = CodeIdentity("b" * 40, "sha256:" + "2" * 64)


def test_success_requires_expected_live_commit_and_digest():
    result = attest_live_commit(NEW, NEW)

    assert result.status is AttestationStatus.SUCCEEDED
    assert result.ok
    assert not result.rollback_required
    assert result.to_dict()["expected"] == NEW.to_dict()


def test_startup_and_health_failures_request_rollback():
    startup = attest_live_commit(NEW, None, startup_ok=False, rollback_target=OLD)
    health = attest_live_commit(NEW, NEW, health_ok=False, rollback_target=OLD)

    assert (startup.status, startup.reason) == (
        AttestationStatus.FAILED,
        "startup_failed",
    )
    assert (health.status, health.reason) == (AttestationStatus.FAILED, "health_failed")
    assert startup.rollback.required and startup.rollback.target == OLD
    assert health.rollback.required and health.rollback.target == OLD


def test_mismatched_live_digest_fails_closed_and_rollback_can_be_attested():
    mismatch = attest_live_commit(
        NEW,
        OLD,
        rollback_target=OLD,
    )
    restored = attest_rollback(OLD, OLD)

    assert mismatch.reason == "live_commit_mismatch"
    assert mismatch.status is AttestationStatus.FAILED
    assert restored.status is AttestationStatus.ROLLED_BACK
    assert restored.reason == "rollback_attested"


def test_loaded_code_digest_is_order_independent():
    first = loaded_code_digest({"pkg/a.py": b"a", "pkg/b.py": b"b"})
    second = loaded_code_digest({"pkg/b.py": b"b", "pkg/a.py": b"a"})

    assert first == second
    assert first.startswith("sha256:")


def test_manual_pull_in_idle_checkout_is_pending():
    result = detect_manual_pull(OLD.commit, NEW.commit)

    assert result.status is PullStatus.PENDING_UPDATE
    assert result.pending
    assert result.reason == "manual_pull"
    assert result.to_dict()["stage_required"] is True


def test_manual_pull_during_update_stays_separate_from_captured_head():
    result = detect_manual_pull(
        OLD.commit,
        NEW.commit,
        update_in_progress=True,
        captured_head=OLD.commit,
    )

    assert result.status is PullStatus.PENDING_UPDATE
    assert result.abort_in_flight_update
    assert result.captured_head == OLD.commit
    assert result.reason == "manual_pull_during_update"


def test_first_head_observation_is_only_a_baseline():
    result = detect_manual_pull(None, OLD.commit)

    assert result.status is PullStatus.BASELINE
    assert not result.pending
