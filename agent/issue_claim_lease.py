"""Durable, fenced issue claims for orchestration workers.

This is the agent-side boundary for the Issue Factory claim contract.  The
lease state is local and durable; GitHub is deliberately behind the small
``ClaimCommentSink`` seam so a network failure cannot turn a retry into a new
comment.  The store uses SQLite's ``BEGIN IMMEDIATE`` to make acquisition a
compare-and-swap operation across worker processes.
"""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

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

    def __post_init__(self) -> None:
        """Normalize and validate values used in persisted lease receipts.

        SQLite returns numeric columns as floats even when a caller supplied
        integer timestamps.  Normalizing at the boundary keeps a receipt
        rendered before persistence byte-identical to one rendered after a
        reload, and rejecting non-finite values prevents a lease that can
        never expire from entering the store.
        """

        for name in ("acquired_at", "ttl_s", "heartbeat_at"):
            value = getattr(self, name)
            try:
                value = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{name} must be finite") from error
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if name == "ttl_s" and value <= 0:
                raise ValueError("ttl_s must be positive")
            object.__setattr__(self, name, value)

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
        self._memory_connection: sqlite3.Connection | None = None
        if self.path == ":memory:":
            # ``sqlite3.connect(':memory:')`` creates a new database per
            # connection.  Keep one connection for this explicitly in-memory
            # store so the same API remains usable by deterministic tests.
            self._memory_connection = sqlite3.connect(
                ":memory:", timeout=30, isolation_level=None
            )
            self._memory_connection.row_factory = sqlite3.Row
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection
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
        try:
            now = float(now)
            ttl_s = float(ttl_s)
        except (TypeError, ValueError) as error:
            raise ValueError("now and ttl_s must be finite numbers") from error
        if not math.isfinite(now) or not math.isfinite(ttl_s):
            raise ValueError("now and ttl_s must be finite numbers")
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
        try:
            now = float(now)
        except (TypeError, ValueError) as error:
            raise ValueError("now must be a finite number") from error
        if not math.isfinite(now):
            raise ValueError("now must be a finite number")
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
                    or now < current.heartbeat_at
                ):
                    connection.commit()
                    return ClaimAttempt("renew_rejected", current, False)
                if now == current.heartbeat_at:
                    connection.commit()
                    return ClaimAttempt("renewed", current, False)
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
                if (
                    current.lease_id != lease.lease_id
                    or current.holder != lease.holder
                    or current.fencing_token != lease.fencing_token
                ):
                    connection.commit()
                    return ClaimAttempt("release_rejected", current, False)
                if current.status == "released":
                    connection.commit()
                    return ClaimAttempt("released", current, False)
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
                """
                UPDATE issue_claims SET comment_id = ?
                WHERE issue = ? AND lease_id = ? AND holder = ?
                  AND fencing_token = ?
                """,
                (
                    comment_id,
                    lease.issue,
                    lease.lease_id,
                    lease.holder,
                    lease.fencing_token,
                ),
            )
        return self.get(lease.issue) or lease

    def sync_comment(
        self,
        lease: ClaimLease,
        *,
        marker: str,
        body: str,
        upsert: Callable[[str, str, str, str | None], str],
    ) -> ClaimLease:
        """Serialize marker discovery/mutation with durable lease state.

        ``acquire`` commits before GitHub I/O so a slow network cannot hold the
        claim transaction.  The follow-up comment operation still needs a
        durable critical section: otherwise two workers can both observe a
        missing ``comment_id`` and POST before either one attaches its result.
        Holding ``BEGIN IMMEDIATE`` across this one existing sink call makes
        the read/discover/upsert/attach sequence one per-issue operation.
        """

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM issue_claims WHERE issue = ?", (lease.issue,)
                ).fetchone()
                if not row:
                    connection.commit()
                    return lease
                current = self._row_to_lease(row)
                if (
                    current.lease_id != lease.lease_id
                    or current.holder != lease.holder
                    or current.fencing_token != lease.fencing_token
                ):
                    connection.commit()
                    return current
                if lease.comment_id is None and current.comment_id is not None:
                    # Another worker completed the same lease's first sync
                    # while this attempt was waiting for the SQLite lock.
                    connection.commit()
                    return current
                comment_id = self._require_text(
                    upsert(current.issue, marker, body, current.comment_id),
                    "comment_id",
                )
                connection.execute(
                    """
                    UPDATE issue_claims SET comment_id = ?
                    WHERE issue = ? AND lease_id = ? AND holder = ?
                      AND fencing_token = ?
                    """,
                    (
                        comment_id,
                        current.issue,
                        current.lease_id,
                        current.holder,
                        current.fencing_token,
                    ),
                )
                updated = ClaimLease(**{**current.__dict__, "comment_id": comment_id})
                connection.commit()
                return updated
            except BaseException:
                connection.rollback()
                raise


class ClaimCoordinator:
    """Pair lease transitions with marker-comment upserts, never posts retries."""

    def __init__(self, store: ClaimLeaseStore, comments: ClaimCommentSink) -> None:
        self.store = store
        self.comments = comments

    def _sync_comment(self, attempt: ClaimAttempt) -> ClaimAttempt:
        if attempt.status == "already_claimed" and attempt.lease.comment_id is None:
            # A prior process may have committed the lease but lost the
            # comment response.  Re-enter the sink so it can discover the
            # marker and patch it; this is the recovery path that prevents
            # an orphaned lease without turning active retries into spam.
            pass
        elif attempt.status not in {"acquired", "taken_over", "renewed", "released"}:
            return attempt
        elif not attempt.changed and attempt.lease.comment_id is not None:
            # Idempotent acquire/release (and a same-timestamp renewal) must
            # not cause an unnecessary edit.  A missing id is still retried.
            return attempt
        lease = attempt.lease
        body = render_claim_comment(lease)
        try:
            lease = self.store.sync_comment(
                lease,
                marker=CLAIM_MARKER,
                body=body,
                upsert=self.comments.upsert,
            )
        except Exception as error:  # comment failure must not create a second one
            return ClaimAttempt(attempt.status, lease, attempt.changed, str(error))
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
        "heartbeat_at": float(lease.heartbeat_at),
        "expires_at": float(lease.expires_at),
    }
    if lease.takeover_reason:
        state["takeover_reason"] = lease.takeover_reason
    return (
        f"{CLAIM_MARKER}\n```json\n"
        f"{json.dumps(state, sort_keys=True, separators=((',', ':')), ensure_ascii=False)}\n```"
    )


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
