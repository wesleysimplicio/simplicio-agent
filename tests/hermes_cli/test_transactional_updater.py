"""Focused tests for the bounded transactional updater façade."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hermes_cli.staging_activation import DetachedRestartIntent, RestartPhase
from hermes_cli.transactional_updater import TransactionalUpdater
from tools.live_commit_attestation import AttestationStatus, CodeIdentity


def _tree(root: Path, value: str) -> None:
    (root / "nested").mkdir(parents=True, exist_ok=True)
    (root / "app.txt").write_text(value, encoding="utf-8")
    (root / "nested" / "version.txt").write_text(value, encoding="utf-8")


def _git_repo(root: Path) -> None:
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "tests@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Tests"], check=True)
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "base"],
        check=True,
        capture_output=True,
    )


def test_preserve_dirty_tree_is_bounded_and_content_addressed(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git_repo(checkout)
    (checkout / "tracked.txt").write_text("local\n", encoding="utf-8")
    (checkout / "local.txt").write_text("untracked\n", encoding="utf-8")

    updater = TransactionalUpdater(tmp_path / "state")
    preservation, receipt = updater.preserve(checkout)

    assert receipt.verified
    assert receipt.base_commit == preservation.manifest.base_commit
    assert receipt.paths == ("local.txt", "tracked.txt")
    assert updater.receipts()[-1]["operation"] == "preserve"


def test_stage_activate_and_rollback_emit_receipts_and_keep_previous(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _tree(first, "one")
    _tree(second, "two")
    updater = TransactionalUpdater(tmp_path / "state")

    first_candidate = updater.stage(first)
    first_receipt = updater.activate(first_candidate)
    second_candidate = updater.stage(second)
    second_receipt = updater.activate(second_candidate)

    assert first_receipt.status == "committed"
    assert second_receipt.before == first_receipt.after
    assert second_receipt.detail == {"previous": first_receipt.after}
    rolled_back = updater.rollback()
    assert rolled_back.after == first_receipt.after
    assert updater.current().current == first_receipt.after
    assert [item["operation"] for item in updater.receipts()] == [
        "stage",
        "activate",
        "stage",
        "activate",
        "rollback",
    ]
    assert len(TransactionalUpdater(tmp_path / "state").receipts()) == 5


def test_failed_health_check_emits_rollback_receipt(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _tree(source, "one")
    updater = TransactionalUpdater(tmp_path / "state")
    first = updater.stage(source)
    updater.activate(first)
    second = updater.stage(source)

    try:
        updater.activate(second, health_check=lambda _manifest: False)
    except RuntimeError as exc:
        assert "rolled back" in str(exc)
    else:
        raise AssertionError("failed health check unexpectedly committed")

    assert updater.receipts()[-1]["status"] == "rolled_back"


def test_restart_receipt_is_observational_and_reports_failed_startup(tmp_path: Path):
    updater = TransactionalUpdater(tmp_path / "state")
    intent = DetachedRestartIntent(12, "candidate", "a" * 64, "test-supervisor")
    events: list[str] = []

    result = updater.restart(
        intent,
        wait_for_drain=lambda _timeout: events.append("drain") or True,
        request_supervisor_restart=lambda _intent: events.append("request") or True,
        wait_for_startup=lambda _intent, _timeout: events.append("startup") or False,
    )

    assert result.phase is RestartPhase.FAILED
    assert events == ["drain", "request", "startup"]
    assert updater.receipts()[-1]["status"] == "failed"


def test_attestation_receipt_requests_rollback_on_mismatch(tmp_path: Path):
    updater = TransactionalUpdater(tmp_path / "state")
    expected = CodeIdentity("a" * 40, "b" * 64)
    observed = CodeIdentity("c" * 40, "d" * 64)

    result = updater.attest(expected, observed)

    assert result.status is AttestationStatus.FAILED
    assert result.rollback_required
    receipt = updater.receipts()[-1]
    assert receipt["operation"] == "attest"
    assert receipt["rollback_required"] is True


def test_rollback_attestation_receipt_is_distinct(tmp_path: Path):
    updater = TransactionalUpdater(tmp_path / "state")
    identity = CodeIdentity("a" * 40, "b" * 64)

    result = updater.attest_rollback(identity, identity)

    assert result.status is AttestationStatus.ROLLED_BACK
    assert updater.receipts()[-1]["operation"] == "attest_rollback"


def test_recover_after_staging_is_idempotent(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _tree(source, "one")
    updater = TransactionalUpdater(tmp_path / "state")
    updater.stage(source)

    first = updater.recover()
    second = updater.recover()

    assert first is None
    assert second is None
    assert [item["operation"] for item in updater.receipts()][-2:] == [
        "recover",
        "recover",
    ]
