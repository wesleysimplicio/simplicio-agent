from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.promotion_controller import (
    PromotionController,
    PromotionReceiptError,
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
