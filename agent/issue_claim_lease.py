"""Durable, fenced issue claims for orchestration workers.

This is the agent-side boundary for the Issue Factory claim contract.  The
lease state is local and durable; GitHub is deliberately behind the small
``ClaimCommentSink`` seam so a network failure cannot turn a retry into a new
comment.  The store uses SQLite's ``BEGIN IMMEDIATE`` to make acquisition a
compare-and-swap operation across worker processes.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

CLAIM_SCHEMA = "simplicio.lease/v1"
CLAIM_MARKER = "<!-- simplicio-claim -->"


class ClaimCommentSink(Protocol):
    """Create or edit the one marker comment belonging to a lease."""

    def upsert(self, issue: str, marker: str, body: str, comment_id: str | None) -> str:
        """Return the stable GitHub comment id after an upsert."""


class LeaseError(RuntimeError):
    """Base error for invalid or stale lease operations."""


@dataclass(frozen=True)
class ClaimLease:
    issue: str
    lease_id: str
    holder: str
    acquired_at: float
    ttl_s: float
    heartbeat_at: float
    fencing_token: int
    status: str = "claimed"
    takeover_reason: str | None = None
    comment_id: str | None = None

    @property
    def expires_at(self) -> float:
        return self.heartbeat_at + self.ttl_s

    def active_at(self, now: float) -> bool:
        # Equality is still active; takeover is allowed only after the TTL.
        return now <= self.expires_at and self.status == "claimed"


@dataclass(frozen=True)
class ClaimAttempt:
    status: str
    lease: ClaimLease
    changed: bool
    comment_error: str | None = None


class ClaimLeaseStore:
    """SQLite-backed CAS lease store shared by issue-factory workers."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS issue_claims (
                    issue TEXT PRIMARY KEY,
                    lease_id TEXT NOT NULL,
                    holder TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    ttl_s REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    takeover_reason TEXT,
                    comment_id TEXT
                )
                """
            )

    @staticmethod
    def _require_text(value: str, name: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError(f"{name} must not be empty")
        return value

    @staticmethod
    def _row_to_lease(row: sqlite3.Row) -> ClaimLease:
        return ClaimLease(**dict(row))

    def get(self, issue: str) -> ClaimLease | None:
        issue = self._require_text(issue, "issue")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM issue_claims WHERE issue = ?", (issue,)
            ).fetchone()
        return self._row_to_lease(row) if row else None

    def acquire(
        self,
        issue: str,
        holder: str,
        *,
        now: float,
        ttl_s: float,
        takeover_reason: str | None = None,
    ) -> ClaimAttempt:
        issue = self._require_text(issue, "issue")
        holder = self._require_text(holder, "holder")
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM issue_claims WHERE issue = ?", (issue,)
                ).fetchone()
                if row:
                    current = self._row_to_lease(row)
                    if current.active_at(now):
                        connection.commit()
                        return ClaimAttempt("already_claimed", current, False)
                    reason = self._require_text(
                        takeover_reason or "expired lease takeover", "takeover_reason"
                    )
                    lease = ClaimLease(
                        issue=issue,
                        lease_id=uuid.uuid4().hex,
                        holder=holder,
                        acquired_at=now,
                        ttl_s=float(ttl_s),
                        heartbeat_at=now,
                        fencing_token=current.fencing_token + 1,
                        takeover_reason=reason,
                        comment_id=current.comment_id,
                    )
                    status = "taken_over"
                else:
                    lease = ClaimLease(
                        issue=issue,
                        lease_id=uuid.uuid4().hex,
                        holder=holder,
                        acquired_at=now,
                        ttl_s=float(ttl_s),
                        heartbeat_at=now,
                        fencing_token=1,
                    )
                    status = "acquired"
                connection.execute(
                    """
                    INSERT INTO issue_claims
                    (issue, lease_id, holder, acquired_at, ttl_s, heartbeat_at,
                     fencing_token, status, takeover_reason, comment_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(issue) DO UPDATE SET
                      lease_id=excluded.lease_id, holder=excluded.holder,
                      acquired_at=excluded.acquired_at, ttl_s=excluded.ttl_s,
                      heartbeat_at=excluded.heartbeat_at,
                      fencing_token=excluded.fencing_token, status=excluded.status,
                      takeover_reason=excluded.takeover_reason,
                      comment_id=excluded.comment_id
                    """,
                    (
                        lease.issue,
                        lease.lease_id,
                        lease.holder,
                        lease.acquired_at,
                        lease.ttl_s,
                        lease.heartbeat_at,
                        lease.fencing_token,
                        lease.status,
                        lease.takeover_reason,
                        lease.comment_id,
                    ),
                )
                connection.commit()
                return ClaimAttempt(status, lease, True)
            except BaseException:
                connection.rollback()
                raise

    def renew(
        self,
        lease: ClaimLease,
        *,
        now: float,
    ) -> ClaimAttempt:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM issue_claims WHERE issue = ?", (lease.issue,)
                ).fetchone()
                if not row:
                    connection.commit()
                    return ClaimAttempt("not_found", lease, False)
                current = self._row_to_lease(row)
                if (
                    current.lease_id != lease.lease_id
                    or current.holder != lease.holder
                    or current.fencing_token != lease.fencing_token
                    or not current.active_at(now)
                ):
                    connection.commit()
                    return ClaimAttempt("renew_rejected", current, False)
                renewed = ClaimLease(**{
                    **current.__dict__,
                    "heartbeat_at": now,
                })
                connection.execute(
                    "UPDATE issue_claims SET heartbeat_at = ? WHERE issue = ?",
                    (now, lease.issue),
                )
                connection.commit()
                return ClaimAttempt("renewed", renewed, True)
            except BaseException:
                connection.rollback()
                raise

    def release(self, lease: ClaimLease) -> ClaimAttempt:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM issue_claims WHERE issue = ?", (lease.issue,)
                ).fetchone()
                if not row:
                    connection.commit()
                    return ClaimAttempt("not_found", lease, False)
                current = self._row_to_lease(row)
                if current.status == "released":
                    connection.commit()
                    return ClaimAttempt("released", current, False)
                if (
                    current.lease_id != lease.lease_id
                    or current.holder != lease.holder
                    or current.fencing_token != lease.fencing_token
                ):
                    connection.commit()
                    return ClaimAttempt("release_rejected", current, False)
                released = ClaimLease(**{**current.__dict__, "status": "released"})
                connection.execute(
                    "UPDATE issue_claims SET status = 'released' WHERE issue = ?",
                    (lease.issue,),
                )
                connection.commit()
                return ClaimAttempt("released", released, True)
            except BaseException:
                connection.rollback()
                raise

    def attach_comment(self, lease: ClaimLease, comment_id: str) -> ClaimLease:
        comment_id = self._require_text(comment_id, "comment_id")
        with self._connect() as connection:
            connection.execute(
                "UPDATE issue_claims SET comment_id = ? WHERE issue = ? AND lease_id = ?",
                (comment_id, lease.issue, lease.lease_id),
            )
        return self.get(lease.issue) or lease


class ClaimCoordinator:
    """Pair lease transitions with marker-comment upserts, never posts retries."""

    def __init__(self, store: ClaimLeaseStore, comments: ClaimCommentSink) -> None:
        self.store = store
        self.comments = comments

    def _sync_comment(self, attempt: ClaimAttempt) -> ClaimAttempt:
        if attempt.status not in {"acquired", "taken_over", "renewed", "released"}:
            return attempt
        lease = attempt.lease
        body = render_claim_comment(lease)
        try:
            comment_id = self.comments.upsert(
                lease.issue, CLAIM_MARKER, body, lease.comment_id
            )
        except Exception as error:  # comment failure must not create a second one
            return ClaimAttempt(attempt.status, lease, attempt.changed, str(error))
        if comment_id != lease.comment_id:
            lease = self.store.attach_comment(lease, comment_id)
        return ClaimAttempt(attempt.status, lease, attempt.changed)

    def acquire(self, *args: Any, **kwargs: Any) -> ClaimAttempt:
        return self._sync_comment(self.store.acquire(*args, **kwargs))

    def renew(self, *args: Any, **kwargs: Any) -> ClaimAttempt:
        return self._sync_comment(self.store.renew(*args, **kwargs))

    def release(self, lease: ClaimLease) -> ClaimAttempt:
        return self._sync_comment(self.store.release(lease))


def render_claim_comment(lease: ClaimLease) -> str:
    """Render a stable, marker-bearing body suitable for GitHub updates."""

    state = {
        "schema": CLAIM_SCHEMA,
        "issue": lease.issue,
        "lease_id": lease.lease_id,
        "holder": lease.holder,
        "fencing_token": lease.fencing_token,
        "status": lease.status,
        "heartbeat_at": lease.heartbeat_at,
        "expires_at": lease.expires_at,
    }
    if lease.takeover_reason:
        state["takeover_reason"] = lease.takeover_reason
    return f"{CLAIM_MARKER}\n```json\n{json.dumps(state, sort_keys=True)}\n```"


class GhIssueCommentSink:
    """GitHub CLI adapter that edits the marker comment instead of reposting."""

    def __init__(self, repository: str, *, gh: str = "gh") -> None:
        self.repository = repository
        self.gh = gh

    def _run(self, args: list[str]) -> str:
        result = subprocess.run(
            [self.gh, *args], capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise LeaseError(result.stderr.strip() or "GitHub comment mutation failed")
        return result.stdout

    def upsert(self, issue: str, marker: str, body: str, comment_id: str | None) -> str:
        if comment_id is None:
            raw = self._run([
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repository}/issues/{issue}/comments",
            ])
            pages = json.loads(raw or "[]")
            comments = [item for page in pages for item in page] if pages else []
            existing = next(
                (item for item in comments if marker in str(item.get("body", ""))),
                None,
            )
            comment_id = str(existing["id"]) if existing else None
        if comment_id is None:
            created = json.loads(
                self._run([
                    "api",
                    f"repos/{self.repository}/issues/{issue}/comments",
                    "--method",
                    "POST",
                    "-f",
                    f"body={body}",
                ])
            )
            return str(created["id"])
        self._run([
            "api",
            f"repos/{self.repository}/issues/comments/{comment_id}",
            "--method",
            "PATCH",
            "-f",
            f"body={body}",
        ])
        return str(comment_id)
