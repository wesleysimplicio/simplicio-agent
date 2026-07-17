from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from agent.issue_claim_lease import (
    CLAIM_MARKER,
    ClaimCoordinator,
    ClaimLease,
    ClaimLeaseStore,
    GhIssueCommentSink,
    render_claim_comment,
)


class FakeComments:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.updated: list[str] = []
        self.failures = 0

    def upsert(self, issue: str, marker: str, body: str, comment_id: str | None) -> str:
        assert marker in body
        if self.failures:
            self.failures -= 1
            raise RuntimeError("comment service unavailable")
        if comment_id is None:
            self.created.append(body)
            return "comment-1"
        self.updated.append(body)
        return comment_id


def make_coordinator(tmp_path: Path) -> tuple[ClaimCoordinator, FakeComments]:
    comments = FakeComments()
    coordinator = ClaimCoordinator(
        ClaimLeaseStore(tmp_path / "claims.sqlite"), comments
    )
    return coordinator, comments


def test_acquire_is_cas_and_idempotent_with_one_comment(tmp_path: Path) -> None:
    coordinator, comments = make_coordinator(tmp_path)

    first = coordinator.acquire("315", "worker-a", now=10, ttl_s=30)
    duplicate = coordinator.acquire("315", "worker-b", now=11, ttl_s=30)
    retry = coordinator.acquire("315", "worker-a", now=12, ttl_s=30)

    assert first.status == "acquired"
    assert duplicate.status == "already_claimed"
    assert retry.status == "already_claimed"
    assert first.lease.lease_id == duplicate.lease.lease_id == retry.lease.lease_id
    assert first.lease.fencing_token == 1
    assert len(comments.created) == 1
    assert comments.updated == []


def test_renewal_edits_marker_comment_and_never_posts_again(tmp_path: Path) -> None:
    coordinator, comments = make_coordinator(tmp_path)
    acquired = coordinator.acquire("315", "worker-a", now=10, ttl_s=30)

    renewed = coordinator.renew(acquired.lease, now=20)
    renewed_again = coordinator.renew(renewed.lease, now=21)

    assert renewed.status == renewed_again.status == "renewed"
    assert renewed.lease.comment_id == "comment-1"
    assert len(comments.created) == 1
    assert len(comments.updated) == 2


def test_comment_failure_is_retried_on_idempotent_acquire(tmp_path: Path) -> None:
    coordinator, comments = make_coordinator(tmp_path)
    comments.failures = 1

    failed = coordinator.acquire("315", "worker-a", now=10, ttl_s=30)
    recovered = coordinator.acquire("315", "worker-a", now=11, ttl_s=30)

    assert failed.status == "acquired"
    assert failed.comment_error == "comment service unavailable"
    assert recovered.status == "already_claimed"
    assert recovered.lease.comment_id == "comment-1"
    assert len(comments.created) == 1
    assert comments.updated == []


def test_same_timestamp_renewal_is_idempotent_and_does_not_edit(tmp_path: Path) -> None:
    coordinator, comments = make_coordinator(tmp_path)
    acquired = coordinator.acquire("315", "worker-a", now=10, ttl_s=30)

    renewed = coordinator.renew(acquired.lease, now=10)

    assert renewed.status == "renewed"
    assert renewed.changed is False
    assert renewed.lease.heartbeat_at == 10
    assert comments.updated == []


def test_clock_regression_cannot_shorten_heartbeat(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)

    rejected = store.renew(acquired.lease, now=9)

    assert rejected.status == "renew_rejected"
    assert rejected.changed is False
    assert store.get("315").heartbeat_at == 10


def test_expired_takeover_increments_fence_and_edits_existing_comment(
    tmp_path: Path,
) -> None:
    coordinator, comments = make_coordinator(tmp_path)
    acquired = coordinator.acquire("315", "worker-a", now=10, ttl_s=30)

    takeover = coordinator.acquire(
        "315", "worker-b", now=41, ttl_s=30, takeover_reason="worker-a timed out"
    )

    assert takeover.status == "taken_over"
    assert takeover.lease.holder == "worker-b"
    assert takeover.lease.fencing_token == 2
    assert takeover.lease.comment_id == "comment-1"
    assert len(comments.created) == 1
    assert len(comments.updated) == 1


def test_stale_holder_cannot_renew_or_release_new_fence(tmp_path: Path) -> None:
    coordinator, _comments = make_coordinator(tmp_path)
    acquired = coordinator.acquire("315", "worker-a", now=10, ttl_s=30)
    takeover = coordinator.acquire("315", "worker-b", now=41, ttl_s=30)

    assert coordinator.renew(acquired.lease, now=42).status == "renew_rejected"
    assert coordinator.release(acquired.lease).status == "release_rejected"
    assert coordinator.release(takeover.lease).status == "released"
    assert coordinator.release(takeover.lease).changed is False


def test_stale_release_is_rejected_even_after_new_fence_releases(
    tmp_path: Path,
) -> None:
    coordinator, _comments = make_coordinator(tmp_path)
    acquired = coordinator.acquire("315", "worker-a", now=10, ttl_s=30)
    takeover = coordinator.acquire("315", "worker-b", now=41, ttl_s=30)
    coordinator.release(takeover.lease)

    stale = coordinator.release(acquired.lease)

    assert stale.status == "release_rejected"
    assert stale.lease.fencing_token == takeover.lease.fencing_token


def test_ttl_boundary_is_active_until_strictly_after_deadline(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)

    at_deadline = store.acquire("315", "worker-b", now=40, ttl_s=30)
    after_deadline = store.acquire("315", "worker-b", now=40.001, ttl_s=30)

    assert at_deadline.status == "already_claimed"
    assert after_deadline.status == "taken_over"


def test_in_memory_store_uses_one_database_for_all_operations() -> None:
    store = ClaimLeaseStore(":memory:")

    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)

    assert store.get("315") == acquired.lease


def test_claim_comment_receipt_is_stable_across_store_reload(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)
    reloaded = store.get("315")

    assert reloaded is not None
    assert render_claim_comment(acquired.lease) == render_claim_comment(reloaded)


def test_github_sink_finds_marker_and_patches_instead_of_posting() -> None:
    sink = GhIssueCommentSink("owner/repo")
    calls: list[list[str]] = []
    responses = [json.dumps([[{"id": 77, "body": f"old {CLAIM_MARKER}"}]]), ""]

    def run(args: list[str]) -> str:
        calls.append(args)
        return responses.pop(0)

    sink._run = run  # type: ignore[method-assign]
    assert sink.upsert("315", CLAIM_MARKER, "new body", None) == "77"
    assert len(calls) == 2
    assert calls[1][1] == "repos/owner/repo/issues/comments/77"
    assert "POST" not in calls[1]


def test_github_sink_posts_once_when_no_marker_comment_exists() -> None:
    sink = GhIssueCommentSink("owner/repo")
    calls: list[list[str]] = []
    responses = [json.dumps([[{"id": 1, "body": "unrelated"}]]), json.dumps({"id": 99})]

    def run(args: list[str]) -> str:
        calls.append(args)
        return responses.pop(0)

    sink._run = run  # type: ignore[method-assign]
    assert sink.upsert("315", CLAIM_MARKER, "new body", None) == "99"
    assert len(calls) == 2
    assert "POST" in calls[1]


def test_github_sink_raises_lease_error_on_gh_failure() -> None:
    from agent.issue_claim_lease import LeaseError

    sink = GhIssueCommentSink("owner/repo")

    import subprocess as _subprocess

    class FakeResult:
        returncode = 1
        stderr = "boom"
        stdout = ""

    real_run = _subprocess.run

    def fake_run(*_args, **_kwargs):
        return FakeResult()

    _subprocess.run = fake_run  # type: ignore[assignment]
    try:
        with pytest.raises(LeaseError, match="boom"):
            sink.upsert("315", CLAIM_MARKER, "body", "77")
    finally:
        _subprocess.run = real_run  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Validation / error-path coverage (anti-tautology: each test would fail if
# the corresponding guard were removed).
# ---------------------------------------------------------------------------


def test_lease_rejects_non_finite_timestamps() -> None:
    with pytest.raises(ValueError, match="must be finite"):
        ClaimLease(
            issue="315",
            lease_id="x",
            holder="worker-a",
            acquired_at=float("nan"),
            ttl_s=30,
            heartbeat_at=10,
            fencing_token=1,
        )


def test_lease_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_s must be positive"):
        ClaimLease(
            issue="315",
            lease_id="x",
            holder="worker-a",
            acquired_at=10,
            ttl_s=0,
            heartbeat_at=10,
            fencing_token=1,
        )


def test_store_rejects_empty_issue_name(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    with pytest.raises(ValueError, match="issue must not be empty"):
        store.acquire("   ", "worker-a", now=10, ttl_s=30)


def test_acquire_rejects_non_finite_now_or_ttl(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    with pytest.raises(ValueError, match="finite numbers"):
        store.acquire("315", "worker-a", now=float("inf"), ttl_s=30)
    with pytest.raises(ValueError, match="finite numbers"):
        store.acquire("315", "worker-a", now=10, ttl_s=float("nan"))
    with pytest.raises(ValueError, match="ttl_s must be positive"):
        store.acquire("315", "worker-a", now=10, ttl_s=-1)


def test_renew_rejects_non_finite_now(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)
    with pytest.raises(ValueError, match="finite number"):
        store.renew(acquired.lease, now=float("nan"))


def test_renew_on_missing_lease_reports_not_found(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)
    store.release(acquired.lease)
    # Delete the row entirely to exercise the "not_found" branch (distinct
    # from a released-but-present row).
    with store._connect() as connection:
        connection.execute("DELETE FROM issue_claims WHERE issue = ?", ("315",))
    result = store.renew(acquired.lease, now=11)
    assert result.status == "not_found"
    assert result.changed is False


def test_release_on_missing_lease_reports_not_found(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)
    with store._connect() as connection:
        connection.execute("DELETE FROM issue_claims WHERE issue = ?", ("315",))
    result = store.release(acquired.lease)
    assert result.status == "not_found"
    assert result.changed is False


def test_acquire_rolls_back_and_reraises_on_internal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    # An existing (expired) row is required so acquire's takeover branch
    # reaches `_row_to_lease` at all.
    store.acquire("315", "worker-a", now=10, ttl_s=30)

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_row_to_lease", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        store.acquire("315", "worker-b", now=41, ttl_s=30)
    # The failed takeover transaction must not have bumped the fence.
    monkeypatch.undo()
    assert store.get("315").holder == "worker-a"
    assert store.get("315").fencing_token == 1


def test_renew_rolls_back_and_reraises_on_internal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_row_to_lease", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        store.renew(acquired.lease, now=11)


def test_release_rolls_back_and_reraises_on_internal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_row_to_lease", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        store.release(acquired.lease)


# ---------------------------------------------------------------------------
# Real concurrency: multiple OS threads racing the same real SQLite file.
# This is not a mock — a bug in the CAS logic (e.g. dropping BEGIN IMMEDIATE)
# would let more than one thread observe "acquired" here.
# ---------------------------------------------------------------------------


def test_concurrent_acquire_on_real_sqlite_file_yields_exactly_one_winner(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "race.sqlite"
    ClaimLeaseStore(db_path)  # pre-create schema once to avoid a table-create race

    winners: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker(name: str) -> None:
        store = ClaimLeaseStore(db_path)
        barrier.wait()
        result = store.acquire("315", name, now=10, ttl_s=30)
        if result.status == "acquired":
            with lock:
                winners.append(name)

    threads = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1


# ---------------------------------------------------------------------------
# Replay harness for the #315 incident: 6 workers racing the same lease
# within the TTL window must produce exactly one active lease and exactly
# one GitHub comment (created once, edited on the remaining idempotent
# attempts) instead of the 6 duplicate "claim" comments from the incident.
# ---------------------------------------------------------------------------


INCIDENT_315_WORKERS = [
    ("smoke-wave-315", 0.0),
    ("smoke-wave-315-v3", 240.0),
    ("smoke-wave-315-v4", 610.0),
    ("smoke-wave-315-codex", 1215.0),
    ("smoke-wave-315-codex-v2", 1980.0),
    ("smoke-wave-315-codex-v4", 2640.0),
]


def test_replay_of_issue_315_incident_yields_one_lease_and_one_comment(
    tmp_path: Path,
) -> None:
    """Reproduces the #315 root cause: 6 distinct workers claimed the same
    issue over ~44 minutes while a prior claim was still (or believed to
    still be) active. With CAS + marker-comment editing, exactly one worker
    should hold the lease and exactly one comment should exist afterwards —
    not the 6 duplicate "claim notice" comments the incident produced.
    """

    coordinator, comments = make_coordinator(tmp_path)
    attempts = [
        coordinator.acquire("315", holder, now=now, ttl_s=3600)
        for holder, now in INCIDENT_315_WORKERS
    ]

    acquired = [a for a in attempts if a.status == "acquired"]
    rejected = [a for a in attempts if a.status == "already_claimed"]

    assert len(acquired) == 1
    assert len(rejected) == 5
    assert acquired[0].lease.holder == INCIDENT_315_WORKERS[0][0]
    # Exactly one comment ever created on the issue — the whole point of #335.
    assert len(comments.created) == 1
    assert comments.updated == []
    final = coordinator.store.get("315")
    assert final is not None
    assert final.holder == INCIDENT_315_WORKERS[0][0]
    assert final.fencing_token == 1
