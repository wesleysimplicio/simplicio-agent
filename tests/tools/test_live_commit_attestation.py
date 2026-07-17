"""Focused tests for the live-commit/pending-manual-pull boundary."""

import pytest

from tools.live_commit_attestation import (
    AttestationStatus,
    CodeIdentity,
    PullStatus,
    RollbackIntent,
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


def test_unchanged_head_is_not_pending():
    result = detect_manual_pull(OLD.commit, OLD.commit)

    assert result.status is PullStatus.UNCHANGED
    assert not result.pending
    assert result.reason == "head_unchanged"


def test_code_identity_rejects_malformed_digest():
    with pytest.raises(ValueError, match="digest must be"):
        CodeIdentity(OLD.commit, "not-a-digest")


def test_code_identity_rejects_malformed_commit():
    with pytest.raises(ValueError, match="commit must be"):
        CodeIdentity("not-a-commit!", OLD.digest)


def test_rollback_intent_rejects_non_boolean_required():
    with pytest.raises(TypeError, match="rollback required must be a boolean"):
        RollbackIntent(required="yes")


def test_rollback_intent_rejects_target_when_not_required():
    with pytest.raises(ValueError, match="non-required rollback cannot have a target"):
        RollbackIntent(required=False, target=OLD)


def test_rollback_intent_requires_reason_when_required():
    with pytest.raises(ValueError, match="required rollback must include a reason"):
        RollbackIntent(required=True, target=OLD, reason="")


def test_healthy_startup_without_live_report_is_unreported():
    result = attest_live_commit(NEW, None)

    assert result.status is AttestationStatus.FAILED
    assert result.reason == "live_commit_unreported"
    assert result.rollback.required


def test_attest_rollback_returns_failed_result_unmodified_when_mismatched():
    result = attest_rollback(OLD, NEW)

    assert result.status is AttestationStatus.FAILED
    assert result.reason == "live_commit_mismatch"


def test_loaded_code_digest_rejects_empty_name():
    with pytest.raises(ValueError, match="non-empty strings"):
        loaded_code_digest({"": b"a"})


def test_loaded_code_digest_reads_path_contents(tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_bytes(b"payload")

    from_path = loaded_code_digest({"module.py": file_path})
    from_bytes = loaded_code_digest({"module.py": b"payload"})

    assert from_path == from_bytes
