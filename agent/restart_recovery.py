"""Bounded restart recovery for effects whose response may have been lost.

This module is deliberately a small durable model, not a process supervisor.
It records the effect identity beside the existing :class:`TaskEnvelope`
content hash and the content-addressed ``Receipt.sha``.  A fresh
``EffectJournal`` can therefore make the safe post-restart decision without
guessing that an absent response means an effect was not committed.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from agent._fastjson import dumps as _dumps, loads as _loads
from agent.task_envelope import TaskEnvelope

EFFECT_RECOVERY_SCHEMA = "simplicio.effect-recovery"
EFFECT_RECOVERY_SCHEMA_VERSION = "simplicio.effect-recovery/v1"


class EffectState(str, Enum):
    """Durable observations for one idempotency key."""

    PENDING = "pending"
    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    UNKNOWN = "unknown"


class RecoveryDecision(str, Enum):
    """Action a restarted worker may take from the durable observation."""

    SKIP_COMMITTED = "skip_committed"
    RETRY = "retry"
    RECONCILE_UNKNOWN = "reconcile_unknown"


class EffectJournalCorruptError(ValueError):
    """Raised when durable journal evidence cannot be reconstructed."""


class EffectStateConflictError(ValueError):
    """Raised when a stale or contradictory observation is appended."""


def _receipt_sha(receipt: Any) -> Optional[str]:
    """Accept an existing ``Receipt`` or its already-persisted sha."""

    if receipt is None:
        return None
    value = getattr(receipt, "sha", receipt)
    if not isinstance(value, str) or not value:
        raise ValueError("receipt must provide a non-empty sha")
    return value


@dataclass(frozen=True)
class EffectRecord:
    """One append-only effect observation tied to a task and envelope."""

    schema: str
    schema_version: str
    effect_id: str
    task_id: str
    correlation_id: str
    idempotency_key: str
    envelope_hash: str
    state: EffectState
    receipt_sha: Optional[str]
    reason: Optional[str]
    recorded_at_ns: int

    def __post_init__(self) -> None:
        if self.schema != EFFECT_RECOVERY_SCHEMA:
            raise ValueError(f"unsupported effect schema {self.schema!r}")
        if self.schema_version != EFFECT_RECOVERY_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported effect schema version {self.schema_version!r}"
            )
        for name in (
            "effect_id",
            "task_id",
            "correlation_id",
            "idempotency_key",
            "envelope_hash",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.state, EffectState):
            object.__setattr__(self, "state", EffectState(self.state))
        if self.state is EffectState.COMMITTED and not self.receipt_sha:
            raise ValueError("committed effects require a receipt_sha")
        if self.state is EffectState.UNKNOWN and not self.reason:
            raise ValueError("unknown effects require an explicit reason")
        if self.recorded_at_ns <= 0:
            raise ValueError("recorded_at_ns must be positive")

    @classmethod
    def pending(
        cls,
        envelope: TaskEnvelope,
        *,
        effect_id: str,
        idempotency_key: str,
        now_ns: Optional[int] = None,
    ) -> "EffectRecord":
        return cls(
            schema=EFFECT_RECOVERY_SCHEMA,
            schema_version=EFFECT_RECOVERY_SCHEMA_VERSION,
            effect_id=effect_id,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            idempotency_key=idempotency_key,
            envelope_hash=envelope.content_hash(),
            state=EffectState.PENDING,
            receipt_sha=None,
            reason=None,
            recorded_at_ns=now_ns or time.time_ns(),
        )

    def resolve(
        self,
        state: EffectState,
        *,
        receipt: Any = None,
        reason: Optional[str] = None,
        now_ns: Optional[int] = None,
    ) -> "EffectRecord":
        state = EffectState(state)
        return replace(
            self,
            state=state,
            receipt_sha=_receipt_sha(receipt) or self.receipt_sha,
            reason=reason,
            recorded_at_ns=now_ns or time.time_ns(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "effect_id": self.effect_id,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "envelope_hash": self.envelope_hash,
            "state": self.state.value,
            "receipt_sha": self.receipt_sha,
            "reason": self.reason,
            "recorded_at_ns": self.recorded_at_ns,
        }

    def to_json(self) -> str:
        return _dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EffectRecord":
        try:
            return cls(
                schema=data["schema"],
                schema_version=data["schema_version"],
                effect_id=data["effect_id"],
                task_id=data["task_id"],
                correlation_id=data["correlation_id"],
                idempotency_key=data["idempotency_key"],
                envelope_hash=data["envelope_hash"],
                state=EffectState(data["state"]),
                receipt_sha=data.get("receipt_sha"),
                reason=data.get("reason"),
                recorded_at_ns=int(data["recorded_at_ns"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EffectJournalCorruptError(f"invalid effect record: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> "EffectRecord":
        try:
            return cls.from_dict(_loads(text))
        except (TypeError, ValueError) as exc:
            if isinstance(exc, EffectJournalCorruptError):
                raise
            raise EffectJournalCorruptError(f"invalid effect JSON: {exc}") from exc

    def content_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecoveryResult:
    """Restart decision; ``should_execute`` is the only retry gate."""

    decision: RecoveryDecision
    observed_state: EffectState
    reason: str
    record: Optional[EffectRecord]

    @property
    def should_execute(self) -> bool:
        return self.decision is RecoveryDecision.RETRY


class EffectJournal:
    """Durable JSONL effect journal with committed-state monotonicity.

    The caller-owned idempotency key is the durable identity.  ``effect_id``
    remains part of the causal receipt, but cannot be changed to make a replay
    look like a new effect after restart.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records: dict[str, EffectRecord] = {}
        self._load()

    @staticmethod
    def _key(record: EffectRecord) -> str:
        return record.idempotency_key

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise EffectJournalCorruptError(f"cannot read journal: {exc}") from exc
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = EffectRecord.from_json(line)
                self._accept(record, persist=False)
            except (EffectJournalCorruptError, EffectStateConflictError) as exc:
                raise EffectJournalCorruptError(
                    f"journal line {line_no}: {exc}"
                ) from exc

    def _accept(self, record: EffectRecord, *, persist: bool) -> EffectRecord:
        key = self._key(record)
        previous = self._records.get(key)
        if previous == record:
            return previous
        if previous is not None:
            if (
                previous.effect_id != record.effect_id
                or previous.task_id != record.task_id
                or previous.correlation_id != record.correlation_id
                or previous.envelope_hash != record.envelope_hash
            ):
                raise EffectStateConflictError(
                    "idempotency key belongs to another causal chain"
                )
            if previous.state is EffectState.COMMITTED:
                raise EffectStateConflictError(
                    f"committed effect {record.effect_id!r} cannot be superseded"
                )
            if record.state is EffectState.PENDING:
                raise EffectStateConflictError(
                    f"pending observation cannot follow {previous.state.value}"
                )
        self._records[key] = record
        if persist:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(record.to_json() + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                if previous is None:
                    self._records.pop(key, None)
                else:
                    self._records[key] = previous
                raise OSError(f"cannot persist effect journal: {exc}") from exc
        return record

    def append(self, record: EffectRecord) -> EffectRecord:
        """Append a record, treating an exact duplicate as an idempotent no-op."""

        return self._accept(record, persist=True)

    def _latest_for_key(self, idempotency_key: str) -> Optional[EffectRecord]:
        return self._records.get(idempotency_key)

    def begin(
        self,
        envelope: TaskEnvelope,
        *,
        effect_id: str,
        idempotency_key: str,
        now_ns: Optional[int] = None,
    ) -> EffectRecord:
        existing = self._latest_for_key(idempotency_key)
        if existing is not None:
            if (
                existing.effect_id != effect_id
                or existing.task_id != envelope.task_id
                or existing.correlation_id != envelope.correlation_id
                or existing.envelope_hash != envelope.content_hash()
            ):
                raise EffectStateConflictError(
                    "idempotency key was reused with a different effect or task envelope"
                )
            # Replaying begin after a restart must observe the durable state;
            # it must not create a fresh pending attempt over a commit.
            return existing
        return self.append(
            EffectRecord.pending(
                envelope,
                effect_id=effect_id,
                idempotency_key=idempotency_key,
                now_ns=now_ns,
            )
        )

    def resolve(
        self,
        envelope: TaskEnvelope,
        *,
        effect_id: str,
        idempotency_key: str,
        state: EffectState,
        receipt: Any = None,
        reason: Optional[str] = None,
        now_ns: Optional[int] = None,
    ) -> EffectRecord:
        current = self._latest_for_key(idempotency_key)
        if current is None:
            raise KeyError(f"no pending effect {effect_id!r} for idempotency key")
        if current.effect_id != effect_id:
            raise EffectStateConflictError(
                "idempotency key belongs to a different effect"
            )
        if (
            current.task_id != envelope.task_id
            or current.correlation_id != envelope.correlation_id
        ):
            raise EffectStateConflictError(
                "effect does not belong to this task envelope"
            )
        if current.envelope_hash != envelope.content_hash():
            raise EffectStateConflictError(
                "effect envelope hash changed during recovery"
            )
        candidate = current.resolve(
            state, receipt=receipt, reason=reason, now_ns=now_ns
        )
        if current.state is EffectState.COMMITTED:
            return current
        if current.state is candidate.state:
            if (
                current.receipt_sha != candidate.receipt_sha
                or current.reason != candidate.reason
            ):
                raise EffectStateConflictError(
                    f"conflicting duplicate {state.value} observation"
                )
            return current
        return self.append(candidate)

    def latest(self, *, effect_id: str, idempotency_key: str) -> Optional[EffectRecord]:
        record = self._latest_for_key(idempotency_key)
        return record if record is not None and record.effect_id == effect_id else None

    def recover(
        self,
        envelope: TaskEnvelope,
        *,
        effect_id: str,
        idempotency_key: str,
    ) -> RecoveryResult:
        record = self._latest_for_key(idempotency_key)
        if record is None:
            return RecoveryResult(
                decision=RecoveryDecision.RECONCILE_UNKNOWN,
                observed_state=EffectState.UNKNOWN,
                reason="no durable effect record exists; commitment is unknown",
                record=None,
            )
        if (
            record.effect_id != effect_id
            or record.task_id != envelope.task_id
            or record.correlation_id != envelope.correlation_id
        ):
            return RecoveryResult(
                decision=RecoveryDecision.RECONCILE_UNKNOWN,
                observed_state=EffectState.UNKNOWN,
                reason=(
                    "idempotency key belongs to a different effect, task, "
                    "or correlation"
                ),
                record=record,
            )
        if record.envelope_hash != envelope.content_hash():
            return RecoveryResult(
                decision=RecoveryDecision.RECONCILE_UNKNOWN,
                observed_state=EffectState.UNKNOWN,
                reason="effect record envelope hash does not match the resumed envelope",
                record=record,
            )
        if record.state is EffectState.COMMITTED:
            return RecoveryResult(
                decision=RecoveryDecision.SKIP_COMMITTED,
                observed_state=record.state,
                reason="durable committed receipt exists; do not retry the effect",
                record=record,
            )
        if record.state is EffectState.NOT_COMMITTED:
            return RecoveryResult(
                decision=RecoveryDecision.RETRY,
                observed_state=record.state,
                reason=record.reason
                or "verifier confirmed the effect was not committed",
                record=record,
            )
        return RecoveryResult(
            decision=RecoveryDecision.RECONCILE_UNKNOWN,
            observed_state=record.state,
            reason=record.reason or "effect has no definitive commit outcome",
            record=record,
        )


__all__ = [
    "EFFECT_RECOVERY_SCHEMA",
    "EFFECT_RECOVERY_SCHEMA_VERSION",
    "EffectState",
    "RecoveryDecision",
    "EffectJournalCorruptError",
    "EffectStateConflictError",
    "EffectRecord",
    "RecoveryResult",
    "EffectJournal",
]
