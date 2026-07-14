from __future__ import annotations

import json
from pathlib import Path

from agent.issue_claim_lease import (
    CLAIM_MARKER,
    ClaimCoordinator,
    ClaimLeaseStore,
    GhIssueCommentSink,
)


class FakeComments:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.updated: list[str] = []

    def upsert(self, issue: str, marker: str, body: str, comment_id: str | None) -> str:
        assert marker in body
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


def test_ttl_boundary_is_active_until_strictly_after_deadline(tmp_path: Path) -> None:
    store = ClaimLeaseStore(tmp_path / "claims.sqlite")
    acquired = store.acquire("315", "worker-a", now=10, ttl_s=30)

    at_deadline = store.acquire("315", "worker-b", now=40, ttl_s=30)
    after_deadline = store.acquire("315", "worker-b", now=40.001, ttl_s=30)

    assert at_deadline.status == "already_claimed"
    assert after_deadline.status == "taken_over"


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
