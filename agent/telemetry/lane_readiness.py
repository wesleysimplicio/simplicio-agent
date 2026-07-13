"""Canonical lane readiness / blocked-state receipts (issue #142).

During governed multi-lane runs the agent can sit in a state where mapper /
handoff artifacts are missing or stale, a mapper/index lock is held, or the
loop needs a wider context surface than it currently has -- and none of that
was previously surfaced as an explicit, machine-readable receipt. The run
would just stall silently (``artifacts_missing``, ``handoff ready=false`` with
reasons like ``no_handoff_targets`` / ``artifacts_not_fresh`` /
``needs_broader_context``), with no first-class contract distinguishing:

* legitimate waiting on mapper/index/handoff artifacts,
* stale or broken state that needs repair (a dead lock, not a live one), and
* genuinely ready-for-handoff state.

This module is a small, deterministic (model-free) evaluator that turns a
lane's raw artifact/lock/handoff facts into one of three canonical states --
``blocked`` -> ``artifacts_ready`` -> ``handoff_ready`` -- each carrying an
explicit list of machine-readable reasons. It never guesses: every reason
maps 1:1 to a concrete fact (an artifact missing, a lock's heartbeat older
than its TTL, a context surface the caller declared required but not
available). See ``docs/LANE_READINESS_RECOVERY.md`` for how a governed lane
should recover from each blocked reason -- notably, a *legitimate* lock is
never treated as something to remove.

Receipts are persisted through the existing append-only receipts ledger
(:mod:`agent.telemetry.receipts`), so the canonical readiness state rides the
same lane-governance reporting path as every other agent-action receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from agent.telemetry.receipts import Receipt, record_receipt

# Default liveness window for a mapper/index lock. A lock younger than this
# (measured from its last heartbeat, falling back to its acquisition time) is
# "legitimate" -- someone is actively working and the lock must not be
# removed. Older than this with no heartbeat is "stale" -- a broken lock
# that is safe to flag for repair.
DEFAULT_LOCK_STALE_AFTER_SECONDS = 15 * 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso8601(value: str) -> Optional[datetime]:
    try:
        text = value.replace("Z", "+00:00") if value.endswith("Z") else value
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class ReadinessState(str, Enum):
    """The canonical readiness state for a governed lane."""

    BLOCKED = "blocked"
    ARTIFACTS_READY = "artifacts_ready"
    HANDOFF_READY = "handoff_ready"


class BlockReason(str, Enum):
    """Machine-readable reasons a lane is not yet handoff-ready.

    Values intentionally match the vocabulary observed in the live incident
    (issue #142): ``.simplicio`` reporting ``artifacts_missing`` and handoff
    ``ready=false`` with ``no_handoff_targets`` / ``artifacts_not_fresh`` /
    ``needs_broader_context``.
    """

    ARTIFACTS_MISSING = "artifacts_missing"
    ARTIFACTS_NOT_FRESH = "artifacts_not_fresh"
    NO_HANDOFF_TARGETS = "no_handoff_targets"
    NEEDS_BROADER_CONTEXT = "needs_broader_context"
    LOCK_STALE = "lock_stale"


class LockStatus(str, Enum):
    """Legitimate-vs-stale classification for a mapper/index lock."""

    NONE = "none"
    LEGITIMATE = "legitimate"
    STALE = "stale"


@dataclass(frozen=True)
class LockInfo:
    """Facts about a mapper/index lock, if one is held.

    A lock is judged by liveness (a recent heartbeat or acquisition
    timestamp), never by age alone and never by removing it to "check". No
    timestamp at all (a lock file with no provenance) cannot prove liveness
    and is treated as stale -- broken state that needs repair, not silent
    trust.
    """

    holder: Optional[str] = None
    acquired_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    stale_after_seconds: int = DEFAULT_LOCK_STALE_AFTER_SECONDS

    def status(self, *, now: Optional[datetime] = None) -> LockStatus:
        if not self.holder:
            return LockStatus.NONE
        reference = self.heartbeat_at or self.acquired_at
        if not reference:
            return LockStatus.STALE
        ts = _parse_iso8601(reference)
        if ts is None:
            return LockStatus.STALE
        now = now or datetime.now(timezone.utc)
        age_seconds = max(0.0, (now - ts).total_seconds())
        return (
            LockStatus.LEGITIMATE
            if age_seconds <= self.stale_after_seconds
            else LockStatus.STALE
        )


@dataclass(frozen=True)
class ArtifactStatus:
    """One artifact a lane's readiness depends on (e.g. a mapper index)."""

    name: str
    present: bool
    fresh: bool = True
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "present": self.present,
            "fresh": self.fresh,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LaneReadinessReceipt:
    """The canonical, machine-readable readiness receipt for one lane."""

    lane_id: str
    state: ReadinessState
    reasons: List[str] = field(default_factory=list)
    missing_context: List[str] = field(default_factory=list)
    lock_status: LockStatus = LockStatus.NONE
    lock_holder: Optional[str] = None
    artifacts: List[ArtifactStatus] = field(default_factory=list)
    handoff_targets: List[str] = field(default_factory=list)
    ts: str = field(default_factory=_utc_now)

    @property
    def blocked(self) -> bool:
        return self.state is ReadinessState.BLOCKED

    @property
    def artifacts_ready(self) -> bool:
        return self.state in (ReadinessState.ARTIFACTS_READY, ReadinessState.HANDOFF_READY)

    @property
    def handoff_ready(self) -> bool:
        return self.state is ReadinessState.HANDOFF_READY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "state": self.state.value,
            "reasons": list(self.reasons),
            "missing_context": list(self.missing_context),
            "lock_status": self.lock_status.value,
            "lock_holder": self.lock_holder,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "handoff_targets": list(self.handoff_targets),
            "ts": self.ts,
        }


def evaluate_lane_readiness(
    *,
    lane_id: str,
    artifacts: Sequence[ArtifactStatus] = (),
    handoff_targets: Sequence[str] = (),
    lock: Optional[LockInfo] = None,
    required_context: Sequence[str] = (),
    available_context: Sequence[str] = (),
    now: Optional[datetime] = None,
) -> LaneReadinessReceipt:
    """Compute the canonical readiness receipt for one governed lane.

    Deterministic and model-free -- the same inputs always produce the same
    state and reasons, so a blocked lane never reports silent non-progress.

    Transition path (the one this module is built to prove, per issue #142's
    acceptance criteria): ``blocked`` -> ``artifacts_ready`` -> ``handoff_ready``.

    * ``blocked`` -- one or more of: artifacts missing, artifacts present but
      stale, a *stale* lock (a legitimate lock is NOT a block condition), or a
      declared-required context surface that is not available.
    * ``artifacts_ready`` -- every artifact is present and fresh, any held
      lock is legitimate, and every required context surface is available --
      but there are no handoff targets yet (``no_handoff_targets``).
    * ``handoff_ready`` -- all of the above, plus at least one handoff target.
    """

    lock = lock or LockInfo()
    lock_status = lock.status(now=now)

    available = set(available_context)
    missing_context = [c for c in required_context if c not in available]

    reasons: List[str] = []

    if not artifacts:
        reasons.append(BlockReason.ARTIFACTS_MISSING.value)
    else:
        if any(not a.present for a in artifacts):
            reasons.append(BlockReason.ARTIFACTS_MISSING.value)
        if any(a.present and not a.fresh for a in artifacts):
            reasons.append(BlockReason.ARTIFACTS_NOT_FRESH.value)

    if lock_status is LockStatus.STALE:
        reasons.append(BlockReason.LOCK_STALE.value)

    if missing_context:
        reasons.append(BlockReason.NEEDS_BROADER_CONTEXT.value)

    if reasons:
        state = ReadinessState.BLOCKED
    elif not handoff_targets:
        state = ReadinessState.ARTIFACTS_READY
        reasons = [BlockReason.NO_HANDOFF_TARGETS.value]
    else:
        state = ReadinessState.HANDOFF_READY

    return LaneReadinessReceipt(
        lane_id=lane_id,
        state=state,
        reasons=reasons,
        missing_context=missing_context,
        lock_status=lock_status,
        lock_holder=lock.holder,
        artifacts=list(artifacts),
        handoff_targets=list(handoff_targets),
    )


def record_lane_readiness_receipt(
    receipt: LaneReadinessReceipt,
    *,
    directory: Optional[Path] = None,
) -> Receipt:
    """Persist ``receipt`` through the existing receipts ledger (P7).

    This is the wire-up into the current lane governance reporting path:
    every evaluation becomes an append-only, content-addressed record
    alongside other agent-action receipts (``.receipts/<sha>.json``),
    identifiable by ``lane_id`` and ``state`` for downstream tooling
    (status commands, dashboards, CI gates).
    """

    payload = f"lane-readiness:{receipt.lane_id}:{receipt.state.value}:{receipt.ts}"
    return record_receipt(
        payload=payload,
        yool_id=f"agent.governance.lane_readiness.{receipt.lane_id}",
        lane="background",
        status="blocked" if receipt.blocked else "ok",
        meta=receipt.to_dict(),
        directory=directory,
    )
