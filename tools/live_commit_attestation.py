"""Bounded contracts for live-commit attestation and manual pull detection.

The updater/supervisor owns process control.  This module only turns the
supervisor's observations into deterministic, JSON-safe results: a live
process must report the expected commit and digest before an update can be
successful, and an unexpected checkout HEAD is a pending update rather than
an implicit activation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping


ATTESTATION_SCHEMA = "simplicio.live-commit-attestation/v1"
PENDING_UPDATE_SCHEMA = "simplicio.pending-update/v1"
_COMMIT = re.compile(r"[0-9a-f]{7,64}\Z")
_DIGEST = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")


class AttestationStatus(str, Enum):
    """Terminal result categories exposed to an updater."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class PullStatus(str, Enum):
    """Result of comparing two authoritative checkout HEAD observations."""

    BASELINE = "baseline"
    UNCHANGED = "unchanged"
    PENDING_UPDATE = "pending_update"


def _canonical_digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError("digest must be a plain or sha256-prefixed SHA-256 value")
    return f"sha256:{value.removeprefix('sha256:')}"


def _commit(value: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ValueError("commit must be a lowercase hexadecimal Git object id")
    return value


@dataclass(frozen=True)
class CodeIdentity:
    """The commit and content digest reported by the live process."""

    commit: str
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "commit", _commit(self.commit))
        object.__setattr__(self, "digest", _canonical_digest(self.digest))

    def to_dict(self) -> dict[str, str]:
        return {"commit": self.commit, "digest": self.digest}


@dataclass(frozen=True)
class RollbackIntent:
    """An explicit request for the caller to restore the pre-update slot."""

    required: bool
    target: CodeIdentity | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.required, bool):
            raise TypeError("rollback required must be a boolean")
        if not self.required and self.target is not None:
            raise ValueError("a non-required rollback cannot have a target")
        if self.required and not self.reason:
            raise ValueError("a required rollback must include a reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "required": self.required,
            "target": self.target.to_dict() if self.target else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AttestationResult:
    """Fail-closed outcome of startup, health, and live-code checks."""

    status: AttestationStatus
    expected: CodeIdentity
    observed: CodeIdentity | None
    startup_ok: bool
    health_ok: bool
    reason: str
    rollback: RollbackIntent

    @property
    def ok(self) -> bool:
        return self.status is AttestationStatus.SUCCEEDED

    @property
    def rollback_required(self) -> bool:
        return self.rollback.required

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ATTESTATION_SCHEMA,
            "status": self.status.value,
            "expected": self.expected.to_dict(),
            "observed": self.observed.to_dict() if self.observed else None,
            "startup_ok": self.startup_ok,
            "health_ok": self.health_ok,
            "reason": self.reason,
            "rollback": self.rollback.to_dict(),
        }


def attest_live_commit(
    expected: CodeIdentity,
    observed: CodeIdentity | None,
    *,
    startup_ok: bool = True,
    health_ok: bool = True,
    rollback_target: CodeIdentity | None = None,
) -> AttestationResult:
    """Evaluate the live update gate without claiming to perform a rollback.

    Startup, health, and attestation are deliberately ordered.  A missing
    live report or any failed probe is never treated as an implicit success.
    The returned rollback intent is consumed by the updater/supervisor.
    """

    if not startup_ok:
        reason = "startup_failed"
    elif not health_ok:
        reason = "health_failed"
    elif observed is None:
        reason = "live_commit_unreported"
    elif observed != expected:
        reason = "live_commit_mismatch"
    else:
        return AttestationResult(
            AttestationStatus.SUCCEEDED,
            expected,
            observed,
            startup_ok,
            health_ok,
            "verified",
            RollbackIntent(False),
        )

    return AttestationResult(
        AttestationStatus.FAILED,
        expected,
        observed,
        startup_ok,
        health_ok,
        reason,
        RollbackIntent(True, rollback_target, reason),
    )


def attest_rollback(
    expected_previous: CodeIdentity,
    observed: CodeIdentity | None,
    *,
    startup_ok: bool = True,
    health_ok: bool = True,
) -> AttestationResult:
    """Verify the old live identity after a caller performs its rollback."""

    result = attest_live_commit(
        expected_previous,
        observed,
        startup_ok=startup_ok,
        health_ok=health_ok,
    )
    if result.ok:
        return AttestationResult(
            AttestationStatus.ROLLED_BACK,
            result.expected,
            result.observed,
            result.startup_ok,
            result.health_ok,
            "rollback_attested",
            RollbackIntent(False),
        )
    return result


def loaded_code_digest(
    files: Mapping[str, bytes | bytearray | memoryview | Path],
) -> str:
    """Compute a stable digest for the code actually loaded by a process.

    Callers provide the process's loaded module/slot bytes, not a second read
    of the checkout being staged.  Names and bytes are length-delimited and
    sorted, making the result independent of filesystem location and mapping
    insertion order.
    """

    digest = hashlib.sha256()
    for name in sorted(files):
        if not isinstance(name, str) or not name:
            raise ValueError("loaded code names must be non-empty strings")
        value = files[name]
        if isinstance(value, Path):
            payload = value.read_bytes()
        else:
            payload = bytes(value)
        encoded_name = name.replace("\\", "/").encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True)
class PendingUpdate:
    """A checkout HEAD change that must enter the normal update flow."""

    status: PullStatus
    previous_head: str | None
    current_head: str
    update_in_progress: bool
    captured_head: str | None
    reason: str

    @property
    def pending(self) -> bool:
        return self.status is PullStatus.PENDING_UPDATE

    @property
    def abort_in_flight_update(self) -> bool:
        return self.pending and self.update_in_progress

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PENDING_UPDATE_SCHEMA,
            "status": self.status.value,
            "previous_head": self.previous_head,
            "current_head": self.current_head,
            "update_in_progress": self.update_in_progress,
            "captured_head": self.captured_head,
            "reason": self.reason,
            "stage_required": self.pending,
            "abort_in_flight_update": self.abort_in_flight_update,
        }


def detect_manual_pull(
    previous_head: str | None,
    current_head: str,
    *,
    update_in_progress: bool = False,
    captured_head: str | None = None,
) -> PendingUpdate:
    """Classify an authoritative checkout HEAD observation.

    A changed HEAD is pending whether the updater is idle or active.  During
    an active update, the captured HEAD remains the only candidate for that
    update and the new HEAD is reported separately, preventing mixed trees.
    """

    current = _commit(current_head)
    previous = _commit(previous_head) if previous_head is not None else None
    captured = _commit(captured_head) if captured_head is not None else None
    if previous is None:
        status, reason = PullStatus.BASELINE, "initial_head_observed"
    elif current == previous:
        status, reason = PullStatus.UNCHANGED, "head_unchanged"
    elif update_in_progress:
        status, reason = PullStatus.PENDING_UPDATE, "manual_pull_during_update"
    else:
        status, reason = PullStatus.PENDING_UPDATE, "manual_pull"
    return PendingUpdate(
        status, previous, current, update_in_progress, captured, reason
    )


__all__ = [
    "ATTESTATION_SCHEMA",
    "PENDING_UPDATE_SCHEMA",
    "AttestationResult",
    "AttestationStatus",
    "CodeIdentity",
    "PendingUpdate",
    "PullStatus",
    "RollbackIntent",
    "attest_live_commit",
    "attest_rollback",
    "detect_manual_pull",
    "loaded_code_digest",
]
