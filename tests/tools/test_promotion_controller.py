from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tools.promotion_controller import (
    HealthCheckReport,
    PromotionController,
    PromotionError,
    PromotionReceiptError,
    PromotionResult,
    RollbackIntent,
    build_promotion_receipt,
    validate_promotion_receipt,
)


def _tree(root: Path, value: str) -> None:
    root.mkdir()
    (root / "commit.txt").write_text(value, encoding="utf-8")


def _receipt(controller: PromotionController, source: Path, before: str, commit: str):
    digest = controller.stage(source)
    return build_promotion_receipt(
        snapshot_before=before,
        candidate_digest=digest,
        promoted_commit=commit,
        fencing_token=1,
    )


def test_promotion_receipt_requires_schema_operation_and_fenced_active_lease() -> None:
    receipt = build_promotion_receipt(
        snapshot_before="a" * 64,
        candidate_digest="b" * 64,
        promoted_commit="new-commit",
        fencing_token=3,
    )
    assert validate_promotion_receipt(receipt) == []

    invalid = json.loads(json.dumps(receipt))
    invalid["lease"]["status"] = "released"
    invalid["schema"] = "simplicio.release/v1"
    errors = validate_promotion_receipt(invalid)
    assert "schema must be simplicio.promotion/v1" in errors
    assert "lease.status must be active" in errors


def test_valid_receipt_atomically_swaps_current_to_verified_slot(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, before, "commit-new")

    result = controller.promote(
        new,
        receipt,
        lambda slot: {
            "healthy": True,
            "commit": "commit-new",
            "digest": receipt["candidate_digest"],
            "smoke": True,
        },
    )

    assert result.promoted is True
    assert result.rolled_back is False
    assert controller.current() == receipt["candidate_digest"]
    assert (controller.slots / receipt["candidate_digest"] / "commit.txt").read_text(
        encoding="utf-8"
    ) == "new"
    assert result.rollback_intent is None


def test_live_commit_mismatch_restores_pointer_and_emits_automatic_rollback_intent(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, before, "commit-new")

    result = controller.promote(
        new,
        receipt,
        lambda _slot: {
            "healthy": True,
            "commit": "commit-old",
            "digest": receipt["candidate_digest"],
        },
    )

    assert result.promoted is False
    assert result.rolled_back is True
    assert result.rollback_requested is True
    assert result.rollback_intent.reason == "live_commit_mismatch"
    assert result.rollback_intent.automatic is True
    assert controller.current() == before
    assert controller.journal.records()[-1].event == "rollback_intent"


def test_live_digest_mismatch_rolls_back_without_committing_candidate(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, before, "commit-new")

    result = controller.promote(
        new,
        receipt,
        lambda _slot: {
            "healthy": True,
            "commit": "commit-new",
            "digest": "c" * 64,
        },
    )

    assert result.rollback_intent.reason == "live_digest_mismatch"
    assert controller.current() == before
    assert not any(record.event == "commit" for record in controller.journal.records())


def test_invalid_or_stale_receipt_never_swaps_pointer(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, "d" * 64, "commit-new")

    with pytest.raises(PromotionReceiptError, match="snapshot_before"):
        controller.promote(new, receipt, lambda _slot: True)
    assert controller.current() == before


def test_validate_promotion_receipt_rejects_non_mapping_and_bad_fields() -> None:
    assert validate_promotion_receipt("not-a-dict") == [
        "promotion receipt must be an object"
    ]

    receipt = build_promotion_receipt(
        snapshot_before="a" * 64,
        candidate_digest="b" * 64,
        promoted_commit="commit",
        fencing_token=1,
    )
    bad = json.loads(json.dumps(receipt))
    bad["operation"] = "demote"
    bad["candidate_digest"] = "too-short"
    bad["promoted_commit"] = ""
    bad["lease"]["fencing_token"] = -1
    del bad["snapshot_before"]
    errors = validate_promotion_receipt(bad)
    assert "operation must be promote" in errors
    assert "candidate_digest must be a 64-character lowercase digest" in errors
    assert "promoted_commit must be a non-empty string" in errors
    assert "lease.fencing_token must be a positive integer" in errors
    assert "snapshot_before must be a 64-character lowercase digest" in errors


def test_validate_promotion_receipt_rejects_missing_or_expired_lease() -> None:
    receipt = build_promotion_receipt(
        snapshot_before="a" * 64,
        candidate_digest="b" * 64,
        promoted_commit="commit",
        fencing_token=1,
        lease_expires_at=100.0,
    )
    errors = validate_promotion_receipt(receipt, now=200.0)
    assert "lease has expired" in errors

    no_lease = json.loads(json.dumps(receipt))
    no_lease["lease"] = "not-a-mapping"
    assert "lease must be an object" in validate_promotion_receipt(no_lease)

    bad_expiry = json.loads(json.dumps(receipt))
    bad_expiry["lease"]["expires_at"] = "not-a-number"
    assert "lease.expires_at must be numeric" in validate_promotion_receipt(
        bad_expiry, now=200.0
    )


def test_stage_rejects_symlink_or_non_directory_source(tmp_path: Path) -> None:
    controller = PromotionController(tmp_path / "state")
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    with pytest.raises(PromotionError, match="real directory"):
        controller.stage(not_a_dir)


def test_stage_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _tree(source, "same")
    controller = PromotionController(tmp_path / "state")
    digest_1 = controller.stage(source)
    digest_2 = controller.stage(source)
    assert digest_1 == digest_2
    assert (controller.slots / digest_1).is_dir()


def test_stage_raises_if_existing_slot_digest_directory_is_corrupted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    _tree(source, "same")
    controller = PromotionController(tmp_path / "state")
    digest = controller.stage(source)
    # Corrupt the already-staged slot so its content no longer matches its
    # own digest; re-staging the same source must detect the mismatch
    # rather than silently reusing the corrupted directory.
    (controller.slots / digest / "commit.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(PromotionError, match="wrong digest"):
        controller.stage(source)


def test_current_returns_none_when_pointer_is_absent(tmp_path: Path) -> None:
    controller = PromotionController(tmp_path / "state")
    assert controller.current() is None


def test_current_raises_on_malformed_pointer_target(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _tree(source, "value")
    controller = PromotionController(tmp_path / "state")
    controller.seed(source)
    controller.pointer.write_text("not-a-slot-path\n", encoding="utf-8")
    with pytest.raises(PromotionError, match="invalid"):
        controller.current()


def test_current_accepts_json_pointer_payload(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _tree(source, "value")
    controller = PromotionController(tmp_path / "state")
    digest = controller.seed(source)
    controller.pointer.write_text(
        json.dumps({"target": f"slots/{digest}"}), encoding="utf-8"
    )
    assert controller.current() == digest


def test_promote_rolls_back_on_health_check_timeout(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, before, "commit-new")

    def slow_health_check(_slot):
        time.sleep(0.5)
        return {"healthy": True, "commit": "commit-new", "digest": receipt["candidate_digest"]}

    result = controller.promote(new, receipt, slow_health_check, timeout_s=0.05)

    assert result.promoted is False
    assert result.rolled_back is True
    assert result.health.reason == "health_check_timeout"
    assert controller.current() == before


def test_promote_treats_zero_timeout_as_immediate_failure(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, before, "commit-new")

    result = controller.promote(new, receipt, lambda _slot: True, timeout_s=0)

    assert result.promoted is False
    assert result.health.reason == "health_check_timeout"
    assert controller.current() == before


def test_promote_rolls_back_when_health_check_raises(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, before, "commit-new")

    def failing_health_check(_slot):
        raise ValueError("probe exploded")

    result = controller.promote(new, receipt, failing_health_check)

    assert result.promoted is False
    assert result.rolled_back is True
    assert result.health.reason == "health_check_error:ValueError"
    assert controller.current() == before


def test_promote_rolls_back_when_smoke_check_fails(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    _tree(old, "old")
    _tree(new, "new")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    receipt = _receipt(controller, new, before, "commit-new")

    result = controller.promote(
        new,
        receipt,
        lambda _slot: {
            "healthy": True,
            "commit": "commit-new",
            "digest": receipt["candidate_digest"],
            "smoke": False,
        },
    )

    assert result.rollback_intent.reason == "health_smoke_failed"
    assert controller.current() == before


def test_promote_rejects_staged_source_that_does_not_match_receipt_digest(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    other = tmp_path / "other"
    _tree(old, "old")
    _tree(new, "new")
    _tree(other, "different-content")
    controller = PromotionController(tmp_path / "state")
    before = controller.seed(old)
    # Build the receipt against `new` but promote a different source tree
    # (`other`) so the staged digest cannot match the receipt's promise.
    receipt = _receipt(controller, new, before, "commit-new")

    with pytest.raises(PromotionReceiptError, match="staged slot digest"):
        controller.promote(other, receipt, lambda _slot: True)
    assert controller.current() == before


def test_health_check_report_from_value_handles_bool_and_invalid_shapes() -> None:
    assert HealthCheckReport.from_value(True).healthy is True
    assert HealthCheckReport.from_value(False).healthy is False

    invalid = HealthCheckReport.from_value(object())
    assert invalid.healthy is False
    assert invalid.reason == "health_check_invalid_response"

    existing = HealthCheckReport(True, commit="c", digest="d")
    assert HealthCheckReport.from_value(existing) is existing


def test_promotion_result_and_rollback_intent_to_dict_serialize_all_fields() -> None:
    health = HealthCheckReport(True, commit="c", digest="d", smoke=True)
    intent = RollbackIntent(reason="live_commit_mismatch", from_digest="a", to_digest="b")
    result = PromotionResult(
        promoted=False,
        rolled_back=True,
        before_digest="b",
        after_digest="a",
        health=health,
        rollback_intent=intent,
    )
    payload = result.to_dict()
    assert payload["rollback_intent"]["reason"] == "live_commit_mismatch"
    assert payload["health"]["commit"] == "c"
    assert result.rollback_requested is True

    clean = PromotionResult(
        promoted=True,
        rolled_back=False,
        before_digest="b",
        after_digest="a",
        health=health,
    )
    assert clean.rollback_requested is False
    assert clean.to_dict()["rollback_intent"] is None
